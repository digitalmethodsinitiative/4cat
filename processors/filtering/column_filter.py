"""
Filter posts by a given column
"""
import re
import csv
import datetime

from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters", "Dale Wahl"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)


class LexicalFilter(BasicProcessor):
    """
    Retain only posts where a given column matches a given value
    """
    type = "column-filter"  # job type ID
    category = "Filtering"  # category
    title = "Filter by column"  # title displayed in UI
    description = "Copies the dataset, retaining only posts where the chosen 'column' (attribute) matches in the " \
                  "configured way. This creates a new, separate dataset you can run analyses on."
    extension = "csv"  # extension of result file, used internally and in UI

    options = {
        "column": {},
        "match-style": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Match as",
            "options": {
                "exact": "is equal to",
                "exact-not": "is not equal to",
                "contains": "contains",
                "contains-not": "does not contain",
                "less-than": "is less than (numerical values only)",
                "greater-than": "is greater than (numerical values only)",
                "before": "is before (dates only)",
                "after": "is after (dates only)",
            },
            "default": "exact"
        },
        "match-value": {
            "type": UserInput.OPTION_TEXT,
            "help": "Match with",
            "default": "",
            "tooltip": "If you want to match with multiple values, separate with commas. Items matching any of the "
                       "provided values will be retained."
        },
        "match-multiple": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Match multiple values",
            "default": "any",
            "options": {
                "any": "Retain if any value matches",
                "all": "Retain if all values match"
            },
            "tooltip": "When matching on multiple values, you can choose to retain items if all provided values "
                       "match, or if any single one matches. Ignored when matching on a single value."
        },
        "record-matches": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Create True/False column for each match string",
            "default": "no",
            "options": {
                "yes": "Yes, create match value columns",
                "no": "No, filter only"
            },
            "tooltip": "Only relevant for 'any' match type. A column is created for each match value and marked True "
                       "if value was found in column."
        }
    }

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Allow processor on CSV files

        :param module: Dataset or processor to determine compatibility with
        """
        return module.is_top_dataset() and module.get_extension() == "csv"

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):

        options = cls.options
        if not parent_dataset:
            return options
        parent_columns = parent_dataset.get_columns()

        if parent_columns:
            parent_columns = {c: c for c in sorted(parent_columns)}
            options["column"] = {
                "type": UserInput.OPTION_CHOICE,
                "options": parent_columns,
                "help": "Filter items on this column"
        }

        return options

    def process(self):
        """
        Reads a CSV file, filtering items that match in the required way, and
        creates a new dataset containing the matching values
        """
        column = self.parameters.get("column", "")
        match_values = [value.strip() for value in self.parameters.get("match-value").split(",")]
        match_style = self.parameters.get("match-style", "")
        match_multiple = self.parameters.get("match-multiple")
        match_function = any if match_multiple == "any" else all
        record_matches = True if self.parameters.get("record-matches") == 'yes' else False
        self.dataset.log('Searching for matches in column %s' % column)
        self.dataset.log('Match values: %s' % ', '.join(match_values))

        if match_style in ("less-than", "greater-than"):
            try:
                match_values = [float(value) for value in match_values]
            except (ValueError, TypeError):
                self.dataset.update_status("Cannot do '%s' comparison with non-numeric value(s)", is_final=True)
                self.dataset.finish(0)
                return

        # pre-process dates to compare to
        elif match_style in ("after", "before"):
            # this is a little inefficient, but we need to make sure the values
            # can actually be interpreted as dates, either via a timestamp or a
            # unix epoch offset
            ok_format = all(
                [re.match(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}", value) for value in match_values])
            if not ok_format:
                try:
                    match_values = [int(value) for value in match_values]
                except (ValueError, TypeError):
                    self.dataset.update_status("Cannot do '%s' comparison with value(s) that are not dates",
                                               is_final=True)
                    self.dataset.finish(0)
                    return
            else:
                match_values = [datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S").timestamp() for value in
                                match_values]

        matching_items = 0
        processed_items = 0
        with self.dataset.get_results_path().open("w", encoding="utf-8") as outfile:
            writer = None

            for item in self.iterate_items(self.source_file):
                if not writer:
                    # first iteration, check if column actually exists
                    if column not in item.keys():
                        self.dataset.update_status("Column '%s' not found in dataset" % column, is_final=True)
                        self.dataset.finish(0)
                        return

                    if match_multiple == "any" and record_matches:
                        fieldnames = list(item.keys()) + match_values
                    else:
                        fieldnames = item.keys()
                    # initialise csv writer - we do this explicitly rather than
                    # using self.write_items_and_finish() because else we have
                    # to store a potentially very large amount of items in
                    # memory which is not a good idea
                    writer = csv.DictWriter(outfile, fieldnames=fieldnames)
                    writer.writeheader()

                processed_items += 1
                if processed_items % 500 == 0:
                    self.dataset.update_status("Processed %i items (%i matching)" % (processed_items, matching_items))

                # Get column to be used in search for matches
                item_column = item.get(column)

                # comparing dates is allowed on both unix timestamps and
                # 'human' timestamps. For that reason, if we *are* indeed
                # comparing dates, do some pre-processing to make sure we can
                # actually compare the value properly.
                if match_style in ("before", "after"):
                    if re.match(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}", item.get(column)):
                        item_column = datetime.datetime.strptime(item.get(column), "%Y-%m-%d %H:%M:%S").timestamp()
                    else:
                        try:
                            item_column = int(item.get(column))
                        except ValueError:
                            self.dataset.update_status(
                                "Invalid date value '%s', cannot determine if before or after" % item.get(column),
                                is_final=True)
                            self.dataset.finish(0)
                            return

                # Compare each match_value with item_column depending on match_style
                match_list = self.get_list_of_matches(match_style, item_column, match_values)
                # Check 'any' or 'all'
                if match_list is not None and match_function(match_list):
                    matches = True

                    # If recording matches, then update the item to include columns for the match_values
                    if match_multiple == "any" and record_matches:
                        for i in range(len(match_values)):
                            # Map the results to the matches
                            item[match_values[i]] = match_list[i]
                else:
                    matches = False

                if matches:
                    writer.writerow(item)
                    matching_items += 1

        if matching_items == 0:
            self.dataset.update_status("No items matched your criteria", is_final=True)

        self.dataset.finish(matching_items)

    def get_list_of_matches(self, match_style, item_column, match_values):
        """
        Depending on the match_style, a list of True/False is returned for each value in match_values compared to
        item_column
        """
        # depending on match type, mark as matching or not one way or
        # another. This could be greatly optimised for some cases, e.g.
        # when there is only a single value to compare to, and
        # short-circuiting for 'any' matches - not clear if worth it.
        if match_style == "exact":
            match_list = [item_column == value for value in match_values]
        elif match_style == "exact-not":
            match_list = [item_column != value for value in match_values]
        elif match_style == "contains":
            match_list = [value in item_column for value in match_values]
        elif match_style == "contains-not":
            match_list = [value not in item_column for value in match_values]
        elif match_style == "after":
            match_list = [value <= item_column for value in match_values]
        elif match_style == "before":
            match_list = [value >= item_column for value in match_values]
        else:
            # wrap this in a try-catch because we cannot be sure that
            # the column we're comparing to contains valid numerical
            # values
            try:
                if match_style == "greater-than":
                    match_list = [float(value) < float(item_column) for value in match_values]
                elif match_style == "less-than":
                    match_list = [float(value) > float(item_column) for value in match_values]
            except (TypeError, ValueError):
                # do not match
                match_list = None

        return match_list

    def after_process(self):
        super().after_process()

        # Request standalone
        self.create_standalone()
