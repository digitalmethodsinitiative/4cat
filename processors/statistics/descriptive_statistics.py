"""
Generate descriptive statistics for numerical columns in the dataset.
"""

from common.lib.exceptions import ProcessorInterruptedException
from common.lib.helpers import UserInput
from backend.lib.processor import BasicProcessor

import numpy as np

__author__ = "4CAT"
__credits__ = ["4CAT"]
__maintainer__ = "4CAT"
__email__ = "4cat@oilab.eu"


class DescriptiveStatistics(BasicProcessor):
    """
    Generate descriptive statistics for numerical columns.
    """
    type = "descriptive_statistics"  # job type ID
    category = "Statistics"  # category
    title = "Descriptive statistics"  # title displayed in UI
    description = "Calculate descriptive statistics (mean, median, std dev, etc.) for numerical columns."
    extension = "csv"  # extension of result file, used internally in UI

    @classmethod
    def get_options(cls, parent_dataset=None, config=None) -> dict:
        options = {
            "columns": {
                "type": UserInput.OPTION_MULTI,
                "help": "Columns to analyze",
                "options": {},
                "default": [],
                "tooltip": "Select columns to calculate statistics for.",
                "inline": True,
            },
            "skip_empty": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Skip empty or invalid values",
                "default": True,
                "tooltip": "Skip rows where values are missing or cannot be converted to numbers",
            }
        }

        # Get the columns for the select columns option
        if parent_dataset:
            parent_columns = parent_dataset.get_columns()
            if parent_columns:
                options["columns"]["options"] = {v: v for v in parent_columns}

        return options

    @staticmethod
    def is_compatible_with(module=None, config=None):
        """
        Determine compatibility

        :param Dataset module:  Module ID to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        :return bool:
        """
        return module.is_top_dataset() and module.get_extension() in ("csv", "ndjson")

    def process(self):
        skip_empty = self.parameters.get("skip_empty", True)
        selected_columns = self.parameters.get("columns", [])
        
        if not selected_columns:
            self.dataset.finish_with_error("Please select at least one column to analyze")
            return

        # Initialize data structure to hold values for each column
        column_data = {col: [] for col in selected_columns}
        skipped_rows = 0
        total_rows = 0

        self.dataset.update_status("Reading values...")
        for item in self.source_dataset.iterate_items():
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while processing values")

            total_rows += 1
            row_valid = True
            row_values = {}

            # First pass: check if we can process this row
            for col in selected_columns:
                val = item.get(col, "")
                
                # Handle empty values
                if val is None or val == "":
                    if not skip_empty:
                        row_valid = False
                        break
                    continue
                
                # Try to convert to float
                try:
                    float_val = float(val)
                    row_values[col] = float_val
                except (ValueError, TypeError):
                    if not skip_empty:
                        self.dataset.finish_with_error(
                            f"Could not convert value '{val}' to number in column '{col}' at row {total_rows}. "
                            f"Enable 'Skip empty or invalid values' to skip these rows."
                        )
                        return
                    row_valid = False
                    break
            
            # Second pass: add valid values to our data structure
            if row_valid and row_values:
                for col in selected_columns:
                    if col in row_values:
                        column_data[col].append(row_values[col])
            else:
                skipped_rows += 1

        if skipped_rows > 0:
            self.dataset.update_status(f"Skipped {skipped_rows} rows with missing or invalid values")

        # Calculate statistics for each column
        results = []
        
        for column in selected_columns:
            if not column_data[column]:
                self.dataset.finish_with_error(f"No valid numerical values found in column '{column}'")
                return
                
            # Convert to numpy array for calculations
            values = np.array(column_data[column])
            
            # Calculate statistics
            stats = {"column": column}

            stats["count"] = len(values)
            stats["mean"] = round(float(np.mean(values)), 5)
            stats["std"] = round(float(np.std(values, ddof=1)), 5)  # Sample standard deviation
            stats["min"] = round(float(np.min(values)), 5)
            stats["max"] = round(float(np.max(values)), 5)
            stats["range"] = round(float(np.max(values) - np.min(values)), 5)
            stats["25%"] = round(float(np.percentile(values, 25)), 5)
            stats["50%"] = round(float(np.median(values)), 5)
            stats["75%"] = round(float(np.percentile(values, 75)), 5)
            stats["iqr"] = round(float(np.percentile(values, 75) - np.percentile(values, 25)), 5)
            stats["population_variance"] = round(float(np.var(values, ddof=0)), 5)
            stats["sample_variance"] = round(float(np.var(values, ddof=1)), 5)

            # Calculate mode using numpy.unique
            unique_values, counts = np.unique(values, return_counts=True)
            max_count = np.max(counts)
            modes = unique_values[counts == max_count]
            if len(modes) == 1:
                stats["mode"] = round(float(modes[0]), 5)
            elif len(modes) > 1:
                # If there are multiple modes, take the smallest one for consistency
                stats["mode"] = round(float(min(modes)), 5)

            results.append(stats)

        if not results:
            self.dataset.finish_with_error("No valid numerical data found in the selected columns")
            return

        # Finish up
        self.dataset.update_status("Saving results")
        self.write_csv_items_and_finish(results)
