"""
Filter posts by a given column
"""
import re
import csv
import datetime

from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
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
        "column": {
            "type": UserInput.OPTION_TEXT,
            "default": "body",
            "help": "Filter items on this column",
            "tooltip": "The column must exist in the dataset when opened as a CSV file (for example: 'body', "
                       "'timestamp' or 'thread_id')"
        },
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
        }
    }

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Allow processor on CSV files

        :param module: Dataset or processor to determine compatibility with
        """
        return module.is_top_dataset() and module.get_extension() == "csv"

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
        date_compare = None
        with self.dataset.get_results_path().open("w", encoding="utf-8") as outfile:
            writer = None

            for item in self.iterate_items(self.source_file):
                if not writer:
                    # first iteration, check if column actually exists
                    if column not in item.keys():
                        self.dataset.update_status("Column '%s' not found in dataset" % column, is_final=True)
                        self.dataset.finish(0)
                        return

                    # initialise csv writer - we do this explicitly rather than
                    # using self.write_items_and_finish() because else we have
                    # to store a potentially very large amount of items in
                    # memory which is not a good idea
                    writer = csv.DictWriter(outfile, fieldnames=item.keys())
                    writer.writeheader()

                processed_items += 1
                if processed_items % 500 == 0:
                    self.dataset.update_status("Processed %i items (%i matching)" % (processed_items, matching_items))

                # comparing dates is allowed on both unix timestamps and
                # 'human' timestamps. For that reason, if we *are* indeed
                # comparing dates, do some pre-processing to make sure we can
                # actually compare the value properly.
                if match_style in ("before", "after"):
                    if re.match(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}", item.get(column)):
                        date_compare = datetime.datetime.strptime(item.get(column), "%Y-%m-%d %H:%M:%S").timestamp()
                    else:
                        try:
                            date_compare = int(item.get(column))
                        except ValueError:
                            self.dataset.update_status("Invalid date value '%s', cannot determine if before or after" % item.get(column), is_final=True)
                            self.dataset.finish(0)
                            return

                # depending on match type, mark as matching or not one way or
                # another. This could be greatly optimised for some cases, e.g.
                # when there is only a single value to compare to, and
                # short-circuiting for 'any' matches - not clear if worth it.
                matches = False
                if match_style == "exact" and match_function([item.get(column) == value for value in match_values]):
                    matches = True
                elif match_style == "exact-not" and match_function([item.get(column) != value for value in match_values]):
                    matches = True
                elif match_style == "contains" and match_function([value in item.get(column) for value in match_values]):
                    matches = True
                elif match_style == "contains-not" and match_function([value not in item.get(column) for value in match_values]):
                    matches = True
                elif match_style == "after" and match_function([value <= date_compare for value in match_values]):
                    matches = True
                elif match_style == "before" and match_function([value >= date_compare for value in match_values]):
                    matches = True
                else:
                    # wrap this in a try-catch because we cannot be sure that
                    # the column we're comparing to contains valid numerical
                    # values
                    try:
                        if match_style == "greater-than" and match_function([float(value) < float(item.get(column)) for value in match_values]):
                            matches = True
                        elif match_style == "less-than" and match_function([float(value) > float(item.get(column)) for value in match_values]):
                            matches = True
                    except (TypeError, ValueError):
                        # do not match
                        pass

                if matches:
                    writer.writerow(item)
                    matching_items += 1

        if matching_items == 0:
            self.dataset.update_status("No items matched your criteria", is_final=True)

        self.dataset.finish(matching_items)

    def after_process(self):
        super().after_process()

        # Request standalone
        self.create_standalone()
