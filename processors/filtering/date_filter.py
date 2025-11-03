"""
Filter posts by a dates
"""
import dateutil.parser
from dateutil.parser import ParserError
from datetime import datetime

from processors.filtering.base_filter import BaseFilter
from common.lib.helpers import UserInput

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class DateFilter(BaseFilter):
    """
    Retain only posts between specific dates
    """
    type = "date-filter"  # job type ID
    category = "Filtering"  # category
    title = "Filter by date"  # title displayed in UI
    description = "Retains posts between given dates. This will create a new dataset."

    options = {
        "daterange": {
            "type": UserInput.OPTION_DATERANGE,
            "help": "Date range:"
        }
    }   
    
    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
        """
        Get processor options

        Offer available columns in a nice dropdown, when possible

        :param DataSet parent_dataset:  Parent dataset
        :param ConfigManager|None config:  Configuration reader (context-aware)
        :return dict:  Processor options
        """
        options = cls.options
        if not parent_dataset:
            return options
        parent_columns = parent_dataset.get_columns()

        if parent_columns:
            parent_columns = {c: c for c in sorted(parent_columns)}
            options["column"] = {
                "type": UserInput.OPTION_CHOICE,
                "options": parent_columns,
                "help": "Timestamp column",
                "default": "timestamp"  # Default column name
        }
        
        return options

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Allow processor on NDJSON and CSV files

        :param module: Module to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        """
        return module.is_top_dataset() and module.get_extension() in ("csv", "ndjson")

    def filter_items(self):
        """
        Create a generator to iterate through items that can be passed to create either a csv or ndjson
        """
        # Column to match
        # 'timestamp' should be a required field in all datasources
        date_column_name = self.parameters.get("column", "timestamp")

        # Process inputs from user
        min_date, max_date = self.parameters.get("daterange")

        # Should not be None
        if not min_date or not max_date:
            self.dataset.update_status("No date range provided", is_final=True)
            self.dataset.finish(0)
            return

        # Convert to datetime for easy comparison
        min_date = datetime.fromtimestamp(min_date).date()
        max_date = datetime.fromtimestamp(max_date).date()

        # Track progress
        processed_items = 0
        invalid_dates = 0
        matching_items = 0
        consecutive_invalid = 0

        # Loop through items
        for mapped_item in self.source_dataset.iterate_items(processor=self):
            # Update 4CAT and user on status
            processed_items += 1
            if processed_items % 500 == 0:
                self.dataset.update_status("Processed %i items (%i matching, %i invalid dates)" % (processed_items, matching_items, invalid_dates))
                self.dataset.update_progress(processed_items / self.source_dataset.num_rows)
            
            if consecutive_invalid > 25:
                # If we have too many consecutive invalid dates, stop processing
                self.dataset.finish_with_error(f"Too many consecutive invalid dates, does {date_column_name} column contain valid dates?")
                return

            # Attempt to parse timestamp
            item_date = mapped_item.get(date_column_name)
            if not item_date:
                # No date provided, skip this item
                invalid_dates += 1
                # Not marking as consecutive invalid because this may not be an error
                continue
            elif type(item_date) is int or (type(item_date) is str and item_date.replace(".", "").isdecimal() and item_date.count(".") <= 1):
                # If the date is a a decimal, parse as timestamp
                try:
                    item_date = datetime.fromtimestamp(float(item_date))
                except (ValueError, OSError):
                    # If the date is not a valid timestamp, skip this item
                    invalid_dates += 1
                    consecutive_invalid += 1
                    continue
            else:
                try:
                    item_date = dateutil.parser.parse(mapped_item.get(date_column_name))
                except ParserError:
                    # If the date is not parsable, skip this item
                    invalid_dates += 1
                    consecutive_invalid += 1
                    continue

            # Reset consecutive invalid count
            consecutive_invalid = 0
            # Only use date for comparison (not time)
            item_date = item_date.date()

            # Reject dates
            if min_date and item_date < min_date:
                continue
            if max_date and item_date > max_date:
                continue

            # Must be a good date!
            matching_items += 1
            yield mapped_item
        
        if matching_items == 0:
            self.dataset.update_status("No items matched your criteria (%i invalid dates)" % invalid_dates, is_final=True)
        elif invalid_dates > 0:
            self.dataset.update_status("Matched %i items (%i processed, %i invalid dates)" % (matching_items, processed_items, invalid_dates), is_final=True)
