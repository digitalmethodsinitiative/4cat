"""
Create a confusion matrix with values of columns
"""
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.helpers import UserInput
from backend.lib.processor import BasicProcessor

from sklearn.metrics import confusion_matrix, ConfusionMatrixDisplay
import matplotlib
import matplotlib.pyplot as plt

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


class ConfusionMatrix(BasicProcessor):
    """
    Create a confusion matrix with values from two columns
    """
    type = "confusion-matrix"  # job type ID
    category = "Statistics"  # category
    title = "Confusion matrix"  # title displayed in UI
    description = "Create a confusion matrix with data from two columns."  # description displayed in UI
    extension = "png"  # extension of result file, used internally and in UI

    @classmethod
    def get_options(cls, parent_dataset=None, config=None) -> dict:
        options = {
            "columns": {
                "type": UserInput.OPTION_TEXT,
                "help": "Column to use for true and predicted values",
                "inline": True,
                "default": "",
                "tooltip": "Column to use for true and predicted values."
            },
            "skip_empty": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Skip empty values",
                "default": False,
                "tooltip": "Selecting this will skip rows where one or both columns do not contain a value"
            }
        }

        # Get the columns for the select columns option
        if parent_dataset and parent_dataset.get_columns():
            columns = parent_dataset.get_columns()
            options["columns"]["type"] = UserInput.OPTION_MULTI
            options["columns"]["options"] = {v: v for v in columns}

        return options

    @staticmethod
    def is_compatible_with(module=None, config=None):
        """
        Determine compatibility

        :param Dataset module:  Module ID to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        :return bool:
        """
        return module.get_extension() in ("csv", "ndjson")

    def process(self):

        skip_empty = self.parameters.get("skip_empty", False)

        # Parse the column names
        columns = self.parameters.get("columns", "")
        if isinstance(columns, str):
            columns = [columns]
        labels = [col.strip() for col in columns]

        if len(labels) != 2:
            self.dataset.finish_with_error("Please specify exactly two columns: true labels and predicted labels.")
            return

        true_label, pred_label = labels
        if true_label not in self.source_dataset.get_columns() or pred_label not in self.source_dataset.get_columns():
            self.dataset.finish_with_error(f"Specified columns not found in the dataset: {labels}")
            return

        # Get values
        y_true = []
        y_pred = []
        count = 1
        for item in self.source_dataset.iterate_items():
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while getting values for confusion matrix")

            val_true = item.get(true_label)
            val_pred = item.get(pred_label)
            if skip_empty and (not val_pred or not val_true):
                self.dataset.update_status(f"Skipping row {count} (no values in both columns)")
                continue
            elif not skip_empty and (not val_pred or not val_true):
                self.dataset.finish_with_error("Make sure that both columns have values in every row or select 'Skip "
                                               "empty values'")
                return

            y_true.append(val_true)
            y_pred.append(val_pred)
            count += 1

        # Create confusion matrix
        matplotlib.use('agg')
        fig, ax = plt.subplots(figsize=(8, 6))
        labels = sorted(list(set(y_true).union(set(y_pred))))
        cm = confusion_matrix(y_true, y_pred, labels=labels)
        disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=labels)
        disp.plot(ax=ax)
        plt.xticks(rotation=45)
        plt.tight_layout()
        ax.invert_xaxis()  #  Ensures lowest label is at the bottom
        ax.set_xlabel(pred_label)
        ax.set_ylabel(true_label)
        fig.savefig(str(self.dataset.get_results_path()))

        # finish up
        self.dataset.update_status("Saving result")
        self.dataset.update_status("Finished")
        self.dataset.finish(1)