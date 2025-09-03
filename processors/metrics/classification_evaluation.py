"""
Generate accuracy, F1, recall, and precision scores for labels in two columns.
"""

from common.lib.exceptions import ProcessorInterruptedException
from common.lib.helpers import UserInput, andify
from backend.lib.processor import BasicProcessor

from sklearn.preprocessing import MultiLabelBinarizer
from sklearn.metrics import precision_score, recall_score, f1_score, accuracy_score, cohen_kappa_score

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


class ClassificationEvaluation(BasicProcessor):
    """
    Generate accuracy, F1, recall, and precision scores for labels in two columns.
    """
    type = "classification_evaluation"  # job type ID
    category = "Metrics"  # category
    title = "Classification evaluation"  # title displayed in UI
    description = ("Use labels from two columns to calculate evaluation metrics (accuracy, precision, recall, F1, "
                   "and Cohen's Kappa). Produces overall and per-label metrics. Also supports multi-label values.")
    extension = "csv"  # extension of result file, used internally and in UI

    @classmethod
    def get_options(cls, parent_dataset=None, config=None) -> dict:
        options = {
            "metrics": {
                "type": UserInput.OPTION_MULTI,
                "help": "Metrics",
                "options": {
                    "accuracy": "Accuracy",
                    "precision": "Precision",
                    "recall": "Recall",
                    "f1": "F1",
                    "cohens_kappa": "Cohen's Kappa",
                },
                "default": ["accuracy", "precision", "recall", "f1"],
                "tooltip": "Which evaluation metrics to calculate.",
                "inline": True,
            },
            "column_true": {
                "type": UserInput.OPTION_CHOICE,
                "help": "True labels",
                "default": "",
                "tooltip": "Column to use for the true labels.",
            },
            "column_pred": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Predicted labels",
                "default": "",
                "tooltip": "Column to use for the predicted labels.",
            },
            "multi_label": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Columns can contain multiple labels",
                "default": False,
                "tooltip": "Labels need to be comma-separated.",
            },
            "precision_average_info": {
                "type": UserInput.OPTION_INFO,
                "help": "When having multi-label values, the precision can be calculated via different strategies. "
                        "<strong>Micro</strong> calculates the overall precision across all labels. </strong>Macro"
                        "</strong> averages the precision across each label so it gives more weight to rare ones. "
                        "<strong>Weigthed</strong> is like Macro, but gives more weight to bigger classes. See "
                        "the [scikit-learn documentation](https://scikit-learn.org/stable/modules/generated/sklearn."
                        "metrics.precision_score.html#sklearn.metrics.precision_score) for further explanation.",
                "requires": "multi_label==true",
            },
            "precision_average": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Precision averaging for multi-label values",
                "options": {
                    "micro": "Micro",
                    "macro": "Macro",
                    "weighted": "Weighted"
                },
                "default": "macro",
                "requires": "multi_label==true",
                "tooltip": "See the scikit-learn references for more information.",
            },
            "skip_empty": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Skip empty values",
                "default": False,
                "tooltip": "Selecting this will skip rows where one or both columns do not contain a value",
            },
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

        skip_empty = self.parameters.get("skip_empty", False)
        multi_label = self.parameters.get("multi_label", False)
        metrics = self.parameters.get("metrics", [])
        if not metrics:
            self.dataset.finish_with_error("Please select at least one evaluation metric")
        get_accuracy = True if "accuracy" in metrics else False
        get_precision = True if "precision" in metrics else False
        precision_average = self.parameters.get("precision_average", "macro")
        get_recall = True if "recall" in metrics else False
        get_f1 = True if "f1" in metrics else False
        get_cohens_kappa = True if "cohens_kappa" in metrics else False

        # Parse the column names
        column_true = self.parameters.get("column_true", "")
        column_pred = self.parameters.get("column_pred", "")
        if not column_true or not column_pred:
            self.dataset.finish_with_error("Please specify which columns contain the true and predicted labels")

        # Get values
        labels_true = []
        labels_pred = []

        # Prepare list of labels
        count = 1

        self.dataset.update_status("Preparing labels")
        for item in self.source_dataset.iterate_items():
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while getting values for confusion matrix")

            label_true = item.get(column_true).strip()
            label_pred = item.get(column_pred).strip()
            count += 1

            if skip_empty and (not label_pred or not label_true):
                self.dataset.update_status(f"Skipping row {count} (no values in both columns)")
                continue
            elif not skip_empty and (not label_pred or not label_true):
                self.dataset.finish_with_error("Make sure that both columns have values in every row or select 'Skip "
                                               "empty values'")
                return

            if type(label_true) not in (str, float, int, bool) or type(label_pred) not in (str, float, int, bool):
                try:
                    label_true = str(label_true)
                    label_pred = str(label_pred)
                except ValueError:
                    self.dataset.update_status(f"Labels '{label_true}' and '{label_pred}' could not be converted to "
                                               f"text (types: {type(label_true)}, {type(label_pred)}), skipping")
                    continue

            # Add labels independently in the case of multi-label values
            if multi_label:
                labels_true.append([label.strip() for label in label_true.split(",") if label])
                labels_pred.append([label.strip() for label in label_pred.split(",") if label])
            else:
                labels_true.append([label_true])
                labels_pred.append([label_pred])

        results = []
        # Support for multiple labels per item
        binarizer = MultiLabelBinarizer()
        true_bin = binarizer.fit_transform(labels_true)
        pred_bin = binarizer.transform(labels_pred)
        all_labels = ["overall"] + list(binarizer.classes_)
        all_labels_str = andify(all_labels) if len(all_labels) < 25 else ", ".join(all_labels) + "..."
        self.dataset.update_status(f"Calculating metrics for {all_labels_str}")

        # Compute metrics
        for i, label in enumerate(all_labels):
            label_metrics = {"label": str(label)}

            true_col = true_bin
            pred_col = pred_bin

            if label != "overall":
                true_col = true_bin[:, i - 1]  # i-1 because first is 'overall'
                pred_col = pred_bin[:, i - 1]

            average = precision_average if label == "overall" else 'binary'
            label = None if label == "overall" else 1  # None returns all values, and else we use 1 because we binarized

            if get_accuracy:
                label_metrics["accuracy"] = round(accuracy_score(true_col, pred_col), 5)
            if get_precision:
                label_metrics["precision"] = round(precision_score(true_col, pred_col, average=average,
                                                                   zero_division=0, pos_label=label), 5)
            if get_recall:
                label_metrics["recall"] = round(recall_score(true_col, pred_col, average=average, pos_label=label), 5)
            if get_f1:
                label_metrics["f1"] = round(f1_score(true_col, pred_col, average=average, pos_label=label), 5)
            if get_cohens_kappa:
                if get_cohens_kappa:
                    if label == "overall":
                        # Average Cohen's Kappa over all labels
                        kappas = [
                            cohen_kappa_score(true_col[:, j], pred_col[:, j])
                            for j in range(true_col.shape[1])
                        ]
                        label_metrics["cohens_kappa"] = round(sum(kappas) / len(kappas), 5)
                    else:
                        # Per-label Cohen's Kappa
                        label_metrics["cohens_kappa"] = round(cohen_kappa_score(true_col.ravel(), pred_col.ravel()), 5)

            label_metrics["support"] = true_col.shape[0] if label == "overall" else true_col.sum()
            results.append(label_metrics)

        # Finish up
        self.dataset.update_status("Saving results")
        self.write_csv_items_and_finish(results)