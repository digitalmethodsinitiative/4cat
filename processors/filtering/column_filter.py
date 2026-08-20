"""
Filter posts by a given column
"""
import re
import datetime

from backend.lib.processor import BasicProcessor
from common.lib.dataset import StatusType
from processors.filtering.base_filter import BaseFilter
from common.lib.helpers import UserInput, convert_to_int
from common.lib.compatibility import Compatibility
from common.lib.exceptions import QueryParametersException

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
    description = ("A flexible and customizable filter that lets you retain items in selected column that match a "
                   "custom requirement. This creates a new dataset.")

    # top-level csv/ndjson datasets
    compatibility = Compatibility(top_dataset_only=True, extensions={"csv", "ndjson"})

    @classmethod
    def get_options(cls, parent_dataset=None, config=None) -> dict:
        """
        Get processor options

        :param parent_dataset DataSet:  An object representing the dataset that
            the processor would be or was run on. Can be used, in conjunction with
            config, to show some options only to privileged users.
        :param config ConfigManager|None config:  Configuration reader (context-aware)
        :return dict:   Options for this processor
        """
        options = {
            "column": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Column"
            },
            "match-style": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Match type",
                "options": {
                    "value-equals": "is equal to",
                    "value-equals-not": "is not equal to",
                    "value-contains": "contains",
                    "value-contains-not": "does not contain",
                    "value-less-than": "is less than (numerical values only)",
                    "value-greater-than": "is greater than (numerical values only)",
                    "date-before": "is before (dates only)",
                    "date-after": "is after (dates only)",
                    "top-top": "is in the top n results for this attribute",
                    "top-bottom": "is in the bottom n results for this attribute"
                },
                "default": "value-equals"
            },
            "strict-top": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Strict cut-off",
                "default": False,
                "tooltip": "If multiple items have a value that would put them in the top/bottom n, discard "
                           "low/high-scoring items until exactly n items are left",
                "requires": "match-style^=top-"
            },
            "top-n": {
                "type": UserInput.OPTION_TEXT,
                "help": "Top n results",
                "coerce_type": int,
                "min": 1,
                "default": 10,
                "requires": "match-style^=top-"
            },
            "match-value": {
                "type": UserInput.OPTION_TEXT,
                "help": "Match with",
                "default": "",
                "tooltip": "If you want to match with multiple values, separate with commas. Items matching any of the "
                        "provided values will be retained.",
                "requires": "match-style^=value-"
            },
            "match-date": {
                "type": UserInput.OPTION_TEXT,
                "help": "Date",
                "default": "",
                "tooltip": "Use this format: 2023-03-25 08:30:00",
                "requires": "match-style^=date-"
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
                        "results.",
                "requires": "match-style^=value-"
            },
            "lowercase": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Convert all text to lowercase for comparison",
                "default": False,
                "requires": ("match-style^=value-", "match-style!$=than")
            }
        }

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

    @staticmethod
    def validate_query(query, request, config):
        """
        Check that the value to compare with fits the chosen match type

        Numerical and date comparisons can only work if the value to compare
        with is a number or a date. Checking this here means the user gets
        immediate feedback in the form, instead of a dataset that fails while
        running. The value fields are only part of the input when the chosen
        match type actually uses them, so they can be checked directly.

        :param dict query:  Parsed user input
        :param request:  Flask request the input arrived in
        :param config:  Configuration reader
        :return dict:  The parameters to store
        """
        if query.get("match-style") in ("value-less-than", "value-greater-than"):
            try:
                [float(value) for value in query.get("match-value", "").split(",")]
            except ValueError:
                raise QueryParametersException("Comparing as a number requires the value to compare with to be "
                                               f"a number; '{query.get('match-value')}' is not.")

        if query.get("match-style") in ("date-after", "date-before"):
            match_date = query.get("match-date", "").strip()
            if not re.match(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}", match_date):
                try:
                    int(match_date)
                except ValueError:
                    raise QueryParametersException("Comparing by date requires the value to compare with to be a "
                                                   "date, either as YYYY-MM-DD hh:mm:ss or as a unix timestamp.")

        return query

    def filter_items(self):
        """
        Create a generator to iterate through items that can be passed to create either a csv or ndjson. Use
        `for item in self.source_dataset.iterate_items(self)` to iterate through items and access the
        underlying data item via item.original.

        :return generator:
        """
        self.dataset.update_status("Searching for matching posts")
        # User Parameters
        force_lowercase = self.parameters.get("lowercase", False)
        # Get match column parameters
        column = self.parameters.get("column", "")
        match_style = self.parameters.get("match-style", "")
        match_multiple = self.parameters.get("match-multiple")
        match_function = any if match_multiple == "any" else all

        ## first, determine what value(s) to match against/compare to
        if match_style in ("date-after", "date-before"):
            # this is a little inefficient, but we need to make sure the values
            # can actually be interpreted as dates, either via a timestamp or a
            # unix epoch offset
            match_date = self.parameters.get("match-date").strip()
            ok_format = re.match(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}", match_date)
            if not ok_format:
                try:
                    match_values = [int(match_date)]
                except (ValueError, TypeError):
                    self.dataset.finish_with_error(f"Cannot do '{match_style}' comparison with value(s) that are not dates")
                    return
            else:
                match_values = [datetime.datetime.strptime(match_date, "%Y-%m-%d %H:%M:%S").timestamp()]

        else:
            match_values = [value.strip().lower() if force_lowercase else value.strip() for value in
                            self.parameters.get("match-value").split(",")]

            if match_style in ("value-less-than", "value-greater-than"):
                try:
                    match_values = [float(value) for value in match_values]
                except (ValueError, TypeError):
                    self.dataset.finish_with_error(f"Cannot do '{match_style}' comparison with non-numeric value(s)")
                    return

        # now do the matching!
        matching_items = 0
        processed_items = 0

        # one branch for top n/bottom n:
        if match_style in ("top-top", "top-bottom"):
            top_overfull = 0
            top_n = convert_to_int(self.parameters.get("top-n"), 10)
            possible_values = {}
            top_or_bottom = "top" if match_style == "top-top" else "bottom"
            strict_top = self.parameters.get("strict-top")
            self.dataset.update_status(f"Determining {top_or_bottom} {top_n:,} values in dataset")

            for item in self.source_dataset.iterate_items():
                processed_items += 1
                if processed_items % 500 == 0:
                    self.dataset.update_status(f"Pre-processing {processed_items:,} items")
                    self.dataset.update_progress(processed_items / self.source_dataset.num_rows * 0.5)
                value = item.get(column)
                if value not in possible_values:
                    possible_values[value] = 0

                possible_values[value] += 1

            top_values = sorted(list(possible_values), reverse=(match_style == "top-top"))[:top_n]
            buckets = {v: 1 for v in top_values}  # will never be decreased if strict_top is False...
            if strict_top:
                budget = top_n
                for value in top_values:
                    # each value gets a set amount of items that can be included
                    buckets[value] = min(possible_values[value], budget)
                    budget -= buckets[value]

            self.dataset.update_status(f"Filtering {top_n:,} items")
            processed_items = 0
            for item in self.source_dataset.iterate_items(processor=self):
                if processed_items % 500 == 0:
                    self.dataset.update_status(f"Processed {processed_items:,} items ({matching_items:,} matching)")
                    self.dataset.update_progress(0.5 + (processed_items / self.source_dataset.num_rows * 0.5))
                processed_items += 1

                value = item.get(column)
                if value not in top_values:
                    continue

                if buckets[value]:
                    if strict_top:
                        buckets[value] -= 1
                    matching_items += 1
                    yield item
                else:
                    # keep track of how many items we skipped because we're at budget
                    top_overfull += 1


            if top_overfull:
                self.dataset.update_status(f"{top_n:,} items filtered. Because more than {top_n:,} items had values "
                                           f"that were in the {top_or_bottom} {top_n:,}, {top_overfull:,} were "
                                           f"excluded.",
                                           status_type=StatusType.WARNING, is_final=True)

        # and one for more straight-forward comparisons:
        else:
            date_compare = None
            for mapped_item in self.source_dataset.iterate_items(processor=self):
                processed_items += 1
                column_value = mapped_item.get(column).strip()
                if processed_items % 500 == 0:
                    self.dataset.update_status(f"Processed {processed_items:,} items ({matching_items:,} matching)")
                    self.dataset.update_progress(processed_items / self.source_dataset.num_rows)

                # comparing dates is allowed on both unix timestamps and
                # 'human' timestamps. For that reason, if we *are* indeed
                # comparing dates, do some pre-processing to make sure we can
                # actually compare the value properly.
                if match_style in ("date-before", "date-after"):
                    # Dates
                    if re.match(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}", column_value):
                        date_compare = datetime.datetime.strptime(column_value, "%Y-%m-%d %H:%M:%S").timestamp()
                    else:
                        try:
                            date_compare = int(column_value)
                        except ValueError:
                            self.dataset.finish_with_error(
                                f"Invalid date value '{column_value}', cannot determine if before or after")
                            return
                elif match_style in ["value-equals", "value-equals-not", "value-contains", "value-contains-not"]:
                    if type(column_value) is str:
                        # Text
                        column_value = column_value.lower() if force_lowercase else column_value
                    elif column_value is None:
                        column_value = ''
                    else:
                        # Int/Float/Date
                        # If date, user may not be aware we normally store dates as timestamps
                        column_value = str(column_value)
                else:
                    # Numerical
                    pass

                # depending on match type, mark as matching or not one way or
                # another. This could be greatly optimised for some cases, e.g.
                # when there is only a single value to compare to, and
                # short-circuiting for 'any' matches - not clear if worth it.
                matches = False
                if match_style == "value-equals" and match_function([column_value == value for value in match_values]):
                    matches = True
                elif match_style == "value-equals-not" and match_function([column_value != value for value in match_values]):
                    matches = True
                elif match_style == "value-contains" and match_function([value in column_value for value in match_values]):
                    matches = True
                elif match_style == "value-contains-not" and match_function(
                        [value not in column_value for value in match_values]):
                    matches = True
                elif match_style == "date-after" and match_function([value <= date_compare for value in match_values]):
                    matches = True
                elif match_style == "date-before" and match_function([value >= date_compare for value in match_values]):
                    matches = True
                else:
                    # wrap this in a try-catch because we cannot be sure that
                    # the column we're comparing to contains valid numerical
                    # values
                    try:
                        if match_style == "value-greater-than" and match_function(
                                [float(value) < float(mapped_item.get(column)) for value in match_values]):
                            matches = True
                        elif match_style == "value-less-than" and match_function(
                                [float(value) > float(mapped_item.get(column)) for value in match_values]):
                            matches = True
                    except (TypeError, ValueError):
                        # do not match
                        pass

                if matches:
                    yield mapped_item
                    matching_items += 1


class ColumnProcessorFilter(ColumnFilter):
    """
    Retain only posts where a given column matches a given value
    """
    type = "column-processor-filter"  # job type ID
    category = "Filtering"  # category
    title = "Filter by value"  # title displayed in UI
    description = "A generic filter that checks whether a value in a selected column matches a custom requirement. "

    # child (non-top-level) csv/ndjson datasets
    compatibility = Compatibility(child_only=True, extensions={"csv", "ndjson"})

    @classmethod
    def is_filter(cls):
        """
        I'm a filter! And so are my children.
        """
        return False

    @classmethod
    def get_extension(cls, parent_dataset=None):
        # We write the parent's file format verbatim into the result file
        # (see BaseFilter.process), so the dataset must be created with the
        # parent's extension — not the BasicProcessor default of "csv". We
        # can't rely on the is_filter() branch in BasicProcessor.get_extension
        # because we deliberately report is_filter() == False for UI purposes.
        if parent_dataset is not None:
            return parent_dataset.get_extension()
        return None

    def after_process(self):
        BasicProcessor.after_process(self)
        # Inherit the source dataset's type and datasource so map_item resolves
        # correctly on the filtered result (especially for NDJSON). Unlike
        # BaseFilter, we deliberately keep this dataset attached to its parent
        # rather than promoting it to a standalone top-level dataset.
        self.dataset.adopt_type(self.source_dataset.type)
        self.dataset.change_datasource(
            self.source_dataset.parameters.get("datasource", self.source_dataset.type)
        )
