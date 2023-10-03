"""
Filter posts by a given column
"""
import re
import datetime

from backend.lib.processor import BasicProcessor
from processors.filtering.base_filter import BaseFilter
from common.lib.helpers import UserInput, convert_to_int

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters", "Dale Wahl"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class ColumnFilter(BaseFilter):
    """
    Retain only posts where a given column matches a given value
    """
    type = "column-filter"  # job type ID
    category = "Filtering"  # category
    title = "Filter by value"  # title displayed in UI
    description = "A generic filter that checks whether a value in a selected column matches a custom requirement. " \
                  "This will create a new dataset."

    options = {
        "column": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Column"
        },
        "match-style": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Match type",
            "options": {
                "exact": "is equal to",
                "exact-not": "is not equal to",
                "contains": "contains",
                "contains-not": "does not contain",
                "less-than": "is less than (numerical values only)",
                "greater-than": "is greater than (numerical values only)",
                "before": "is before (dates only)",
                "after": "is after (dates only)",
                "top": "is in the top n results for this attribute (use 'Match with' for n)",
                "bottom": "is in the bottom n results for this attribute (use 'Match with' for n)"
            },
            "default": "exact"
        },
        "match-value": {
            "type": UserInput.OPTION_TEXT,
            "help": "Match with",
            "default": "",
            "tooltip": "If you want to match with multiple values, separate with commas. Items matching any of the "
                       "provided values will be retained. Dates in 2023-03-25 08:30:00 format."
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
                       "match, or if any single one matches. Ignored when matching on a single value or selecting top "
                       "results."
        },
        "lowercase": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Convert all text to lowercase for comparison",
            "default": False
        }
    }

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow processor on top datasets.

        :param module: Module to determine compatibility with
        """
        return module.is_top_dataset()

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
                "help": "Column"
        }
        
        return options

    def filter_items(self):
        """
        Create a generator to iterate through items that can be passed to create either a csv or ndjson. Use
        `for original_item, mapped_item in self.source_dataset.iterate_mapped_items(self)` to iterate through items
        and yield `original_item`.

        :return generator:
        """
        self.dataset.update_status("Searching for matching posts")
        # User Parameters
        force_lowercase = self.parameters.get("lowercase", False)
        # Get match column parameters
        column = self.parameters.get("column", "")
        match_values = [value.strip().lower() if force_lowercase else value.strip() for value in self.parameters.get("match-value").split(",")]
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

        elif match_style in ("top", "bottom"):
            for item in self.filter_top(column, match_values[0], (match_style=="bottom")):
                yield item

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
                    self.dataset.update_status("Cannot do '%s' comparison with value(s) that are not dates" % match_style,
                                               is_final=True)
                    self.dataset.finish(0)
                    return
            else:
                match_values = [datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S").timestamp() for value in
                                match_values]

        matching_items = 0
        processed_items = 0
        date_compare = None
        for original_item, mapped_item in self.source_dataset.iterate_mapped_items(self):
            processed_items += 1
            if processed_items % 500 == 0:
                self.dataset.update_status("Processed %i items (%i matching)" % (processed_items, matching_items))
                self.dataset.update_progress(processed_items / self.source_dataset.num_rows)

            # comparing dates is allowed on both unix timestamps and
            # 'human' timestamps. For that reason, if we *are* indeed
            # comparing dates, do some pre-processing to make sure we can
            # actually compare the value properly.
            if match_style in ("before", "after"):
                # Dates
                if re.match(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}", mapped_item.get(column)):
                    date_compare = datetime.datetime.strptime(mapped_item.get(column), "%Y-%m-%d %H:%M:%S").timestamp()
                else:
                    try:
                        date_compare = int(mapped_item.get(column))
                    except ValueError:
                        self.dataset.update_status(
                            "Invalid date value '%s', cannot determine if before or after" % mapped_item.get(column),
                            is_final=True)
                        self.dataset.finish(0)
                        return
            elif match_style in ["exact", "exact-not", "contains", "contains-not"]:
                if type(mapped_item.get(column)) == str:
                    # Text
                    column_value = mapped_item.get(column).lower() if force_lowercase else mapped_item.get(column)
                elif mapped_item.get(column) is None:
                    column_value = ''
                else:
                    # Int/Float/Date
                    # If date, user may not be aware we normally store dates as timestamps
                    column_value = mapped_item.get(column)
                    # TODO: in order to use these match_styles on numerical data (e.g. "views == 1") we need to attempt to convert the match_values from strings
            else:
                # Numerical
                pass

            # depending on match type, mark as matching or not one way or
            # another. This could be greatly optimised for some cases, e.g.
            # when there is only a single value to compare to, and
            # short-circuiting for 'any' matches - not clear if worth it.
            matches = False
            if match_style == "exact" and match_function([column_value == value for value in match_values]):
                matches = True
            elif match_style == "exact-not" and match_function([column_value != value for value in match_values]):
                matches = True
            elif match_style == "contains" and match_function([value in column_value for value in match_values]):
                matches = True
            elif match_style == "contains-not" and match_function(
                    [value not in column_value for value in match_values]):
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
                    if match_style == "greater-than" and match_function(
                            [float(value) < float(mapped_item.get(column)) for value in match_values]):
                        matches = True
                    elif match_style == "less-than" and match_function(
                            [float(value) > float(mapped_item.get(column)) for value in match_values]):
                        matches = True
                except (TypeError, ValueError):
                    # do not match
                    pass

            if matches:
                yield original_item
                matching_items += 1

    def filter_top(self, column, top_n, bottom=False):
        """
        Filter top n items

        :param str column:  Column to rank by
        :param int top_n:  Number of items to return/top n items
        :param bool bottom:  If true, return bottom results instead
        :return:
        """
        possible_values = set()
        top_n = convert_to_int(top_n, 10)
        for item in self.source_dataset.iterate_items():
            possible_values.add(item.get(column))

        ranked_items = 0
        top_values = sorted(list(possible_values), reverse=(not bottom))[:top_n]
        for original_item, item in self.source_dataset.iterate_mapped_items():
            if item.get(column) in top_values:
                ranked_items = 0
                yield original_item

            if ranked_items >= top_n:
                return


class ColumnProcessorFilter(ColumnFilter):
    """
    Retain only posts where a given column matches a given value
    """
    type = "column-processor-filter"  # job type ID
    category = "Filtering"  # category
    title = "Filter by value"  # title displayed in UI
    description = "A generic filter that checks whether a value in a selected column matches a custom requirement. "

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow processor on top datasets.

        :param module: Dataset or processor to determine compatibility with
        """
        return module.get_extension() in ("csv", "ndjson") and not module.is_top_dataset()

    @classmethod
    def is_filter(cls):
        """
        I'm a filter! And so are my children.
        """
        return False

    def after_process(self):
        BasicProcessor.after_process(self)
