"""
Collapse post bodies into one long string
"""

from common.lib.helpers import UserInput, pad_interval, get_interval_descriptor
from backend.lib.processor import BasicProcessor

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

class CountPosts(BasicProcessor):
    """
    Count items in a dataset
    """

    type = "count-posts"  # job type ID
    category = "Metrics"  # category
    title = "Count items per date"  # title displayed in UI
    description = "Counts how many items are in the dataset per date (or overall)."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    followups = ["histogram"]

    @staticmethod
    def is_compatible_with(module=None, config=None):
        """
        Determine compatibility

        :param Dataset module:  Module ID to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        :return bool:
        """
        return module.is_top_dataset() and module.get_extension() in ("csv", "ndjson")

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
        options = {
            "column": {
                "type": UserInput.OPTION_TEXT,
                "default": "timestamp",
                "help": "Column with timestamp",
            },
            "timeframe": {
                "type": UserInput.OPTION_CHOICE,
                "default": "month",
                "options": {
                    "all": "Overall",
                    "year": "Year",
                    "month": "Month",
                    "week": "Week",
                    "day": "Day",
                    "hour": "Hour",
                    "minute": "Minute",
                },
                "help": "Produce counts per",
            },
            "pad": {
                "type": UserInput.OPTION_TOGGLE,
                "default": True,
                "help": "Include dates where the count is zero",
                "tooltip": "Makes the counts continuous. For example, if there are items from May and July but not June, June will be included with 0 items.",
            },
        }

        # Get the columns for the select columns option
        if parent_dataset and parent_dataset.get_columns():
            columns = parent_dataset.get_columns()
            options["column"]["type"] = UserInput.OPTION_MULTI
            options["column"]["inline"] = True
            options["column"]["tooltip"] = "Choose one. If multiple are selected, the first will be used."
            options["column"]["options"] = {v: v for v in columns if "time" in v or "date" in v or "created" in v}
            options["column"]["default"] = (
                "timestamp"
                if "timestamp" in columns
                else sorted(columns, key=lambda k: "time" in k).pop()
            )

        return options

    def process(self):
        """
        This takes a 4CAT results file as input, and outputs a plain text file
        containing all post bodies as one continuous string, sanitized.
        """

        # OrderedDict because dates and headers should have order.
        intervals = {}

        timeframe = self.parameters.get("timeframe")
        column = self.parameters.get("column")
        if not column:
            self.dataset.update_status("No column selected", is_final=True)
            return
        column = column[0] if isinstance(column, list) else column

        unknown_dates = (
            0  # separate counter as padding will not interpret this correctly
        )

        first_interval = "9999"
        last_interval = "0000"

        self.dataset.update_status("Processing items")
        with self.dataset.get_results_path().open("w"):
            counter = 0

            for post in self.source_dataset.iterate_items(self):
                # Ensure the post has a date
                if timeframe != "all" and not post.get(column):
                    # Count these as "unknown_date"
                    unknown_dates += 1
                else:
                    try:
                        date = get_interval_descriptor(post, timeframe, item_column=column)
                    except ValueError as e:
                        self.dataset.update_status(
                            f"{e}, cannot count items per {timeframe}", is_final=True
                        )
                        self.dataset.update_status(0)
                        return

                    # Add a count for the respective timeframe
                    if date not in intervals:
                        intervals[date] = {}
                        intervals[date]["absolute"] = 1
                    else:
                        intervals[date]["absolute"] += 1

                    first_interval = min(first_interval, date)
                    last_interval = max(last_interval, date)

                counter += 1

                if counter % 2500 == 0:
                    self.dataset.update_status(
                        f"Counted {counter:,} of {self.source_dataset.num_rows:,} items."
                    )
                    self.dataset.update_progress(counter / self.source_dataset.num_rows)

            # pad interval if needed, this is useful if the result is to be
            # visualised as a histogram, for example
            if self.parameters.get("pad") and timeframe != "all":
                missing, intervals = pad_interval(
                    intervals, first_interval, last_interval
                )
                if intervals:
                    # Convert 0 values to dict
                    for k, v in intervals.items():
                        if isinstance(v, int):
                            intervals[k] = {"absolute": v}

            rows = []
            # Add unknown dates if needed
            if unknown_dates > 0:
                rows.append(
                    {"date": "unknown_date", "item": "activity", "value": unknown_dates}
                )

            for interval in intervals:
                row = {
                    "date": interval,
                    "item": "activity",
                    "value": intervals[interval]["absolute"],
                }

                rows.append(row)

        if rows:
            self.write_csv_items_and_finish(rows)
        else:
            return self.dataset.finish_with_error(
                "No items could be counted. See dataset log for details"
            )