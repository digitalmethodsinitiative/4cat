"""
Generate MAE, MSE, R2, and RMSE scores for numerical values in two columns.
"""

from common.lib.exceptions import ProcessorInterruptedException
from common.lib.helpers import UserInput
from backend.lib.processor import BasicProcessor

from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import numpy as np

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


class RegressionEvaluation(BasicProcessor):
    """
    Generate MAE, MSE, R2, and RMSE scores for numerical predictions.
    """
    type = "regression_evaluation"  # job type ID
    category = "Statistics"  # category
    title = "Regression evaluation"  # title displayed in UI
    description = ("Calculate regression metrics (MAE, MSE, R2, RMSE) between two numerical columns.")
    extension = "csv"  # extension of result file, used internally in UI

    @classmethod
    def get_options(cls, parent_dataset=None, config=None) -> dict:
        options = {
            "metrics": {
                "type": UserInput.OPTION_MULTI,
                "help": "Metrics to calculate",
                "options": {
                    "mae": "Mean Absolute Error (MAE)",
                    "mse": "Mean Squared Error (MSE)",
                    "rmse": "Root Mean Squared Error (RMSE)",
                    "r2": "R-squared (R²)",
                },
                "default": ["mae", "mse", "rmse", "r2"],
                "tooltip": "Select which regression metrics to calculate.",
                "inline": True,
            },
            "column_true": {
                "type": UserInput.OPTION_CHOICE,
                "help": "True values",
                "default": "",
                "tooltip": "Column containing the true/actual numerical values.",
            },
            "column_pred": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Predicted values",
                "default": "",
                "tooltip": "Column containing the predicted numerical values.",
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
                options["column_true"]["options"] = {v: v for v in parent_columns}
                options["column_pred"]["options"] = {v: v for v in parent_columns}

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
        metrics = self.parameters.get("metrics", ["mae", "mse", "rmse", "r2"])
        
        if not metrics:
            self.dataset.finish_with_error("Please select at least one evaluation metric")
            return
            
        # Get which metrics to calculate
        get_mae = "mae" in metrics
        get_mse = "mse" in metrics
        get_rmse = "rmse" in metrics
        get_r2 = "r2" in metrics

        # Parse the column names
        column_true = self.parameters.get("column_true", "")
        column_pred = self.parameters.get("column_pred", "")
        
        if not column_true or not column_pred:
            self.dataset.finish_with_error("Please specify which columns contain the true and predicted values")
            return

        # Get values
        true_values = []
        pred_values = []
        row_count = 0
        skipped_rows = 0

        self.dataset.update_status("Reading values...")
        for item in self.source_dataset.iterate_items():
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while processing values")

            true_val = item.get(column_true)
            pred_val = item.get(column_pred)
            row_count += 1

            # Skip empty values if configured to do so
            if skip_empty and (true_val is None or pred_val is None or true_val == "" or pred_val == ""):
                skipped_rows += 1
                continue
                
            # Try to convert to float
            try:
                true_float = float(true_val)
                pred_float = float(pred_val)
                true_values.append(true_float)
                pred_values.append(pred_float)
            except (ValueError, TypeError):
                if not skip_empty:
                    self.dataset.finish_with_error(
                        f"Could not convert values to numbers in row {row_count} "
                        f"(true: '{true_val}', predicted: '{pred_val}'). "
                        f"Enable 'Skip empty or invalid values' to skip these rows."
                    )
                    return
                skipped_rows += 1

        if not true_values or not pred_values:
            self.dataset.finish_with_error("No valid numerical values found in the specified columns")
            return
            
        if len(true_values) != len(pred_values):
            self.dataset.finish_with_error("Mismatch in number of true and predicted values")
            return
            
        if skipped_rows > 0:
            self.dataset.update_status(f"Skipped {skipped_rows} rows with missing or invalid values")

        # Convert to numpy arrays for calculations
        true_array = np.array(true_values)
        pred_array = np.array(pred_values)
        
        # Calculate metrics
        results = []
        
        if get_mae:
            mae = mean_absolute_error(true_array, pred_array)
            results.append({
                "metric": "MAE",
                "value": round(mae, 5)
            })
            
        if get_mse:
            mse = mean_squared_error(true_array, pred_array)
            results.append({
                "metric": "MSE",
                "value": round(mse, 5)
            })
            
        if get_rmse:
            rmse = np.sqrt(mean_squared_error(true_array, pred_array))
            results.append({
                "metric": "RMSE",
                "value": round(rmse, 5)
            })
            
        if get_r2:
            r2 = r2_score(true_array, pred_array)
            results.append({
                "metric": "R²",
                "value": round(r2, 5)
            })

        # Finish up
        self.dataset.update_status("Saving results")
        self.write_csv_items_and_finish(results)