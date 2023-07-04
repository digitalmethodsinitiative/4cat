"""
Filter posts by a dates
"""
import dateutil.parser
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
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow processor on NDJSON and CSV files

        :param module: Module to determine compatibility with
        """
        return module.is_top_dataset() and module.get_extension() in ("csv", "ndjson")

    def filter_items(self):
        """
        Create a generator to iterate through items that can be passed to create either a csv or ndjson
        """
        # Column to match
        # 'timestamp' should be a required field in all datasources
        date_column_name = 'timestamp'

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

        # Loop through items
        for original_item, mapped_item in self.source_dataset.iterate_mapped_items(self):
            # Update 4CAT and user on status
            processed_items += 1
            if processed_items % 500 == 0:
                self.dataset.update_status("Processed %i items (%i matching, %i invalid dates)" % (processed_items, matching_items, invalid_dates))
                self.dataset.update_progress(processed_items / self.source_dataset.num_rows)

            # Attempt to parse timestamp
            item_date = dateutil.parser.parse(mapped_item.get(date_column_name))

            # Only use date for comparison (not time)
            item_date = item_date.date()

            # Reject dates
            if min_date and item_date < min_date:
                continue
            if max_date and item_date > max_date:
                continue

            # Must be a good date!
            matching_items += 1
            yield original_item
