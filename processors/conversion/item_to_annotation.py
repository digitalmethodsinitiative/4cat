"""
Change a dataset item to an annotation
"""
from common.lib.exceptions import ProcessorInterruptedException
from backend.lib.processor import BasicProcessor
from common.lib.helpers import UserInput

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


class ItemToAnnotation(BasicProcessor):
    """
	Change a dataset item to an annotation
    """
    type = "item-to-annotation"  # job type ID
    category = "Conversion"  # category
    title = "Convert items to annotations"  # title displayed in UI
    description = ("Convert a regular dataset item to an annotation. This will show it as a separate value in the "
                   "Explorer. Item values must be numbers or strings.")  # description displayed in UI
    extension = "csv"

    @classmethod
    def get_options(cls, parent_dataset=None, config=None) -> dict:

        options = {
            "columns": {
                "type": UserInput.OPTION_TEXT,
                "default": "body",
                "help": "Columns with texts to replace",
            }
        }

        # Get the columns for the select columns option
        if parent_dataset and parent_dataset.get_columns():
            columns = parent_dataset.get_columns()
            options["columns"]["type"] = UserInput.OPTION_MULTI
            options["columns"]["inline"] = True
            options["columns"]["options"] = {v: v for v in columns}

        return options

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Allow processor on NDJSON and CSV files

        :param module: Module to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        """
        return module.get_extension() in ("csv", "ndjson")

    def process(self):
        """
        :return generator:
        """

        # Get column parameters
        columns = self.parameters.get("columns", [])
        if not columns:
            self.dataset.finish_with_error("Please indicate from which column items should be converted")
            return

        if isinstance(columns, str):
            columns = [columns]

        self.dataset.update_status("Reading source file")

        # keep some stats
        converted = 0

        annotations = []

        for i, item in enumerate(self.source_dataset.iterate_items()):
            if self.interrupted:
                raise ProcessorInterruptedException(
                    "Interrupted while replacing texts"
                )

            # Convert text in every column
            for column in columns:

                if item[column]:

                    item_value = item[column]

                    if type(item_value) not in (str, int, float):
                        continue

                    annotated_item = {
                        "label": f"annotation_{column}",
                        "item_id": item["id"],
                        "value": item_value
                    }

                    annotations.append(annotated_item)
                    converted += 1

            if converted % 2500 == 0:
                self.save_annotations(annotations, source_dataset=self.source_dataset)
                annotations = []
                self.dataset.update_status(
                    f"Converted {converted} items into annotations"
                )
                self.dataset.update_progress(
                    i / self.source_dataset.num_rows
                )

        # Write leftover annotations
        if annotations:
            self.save_annotations(annotations, source_dataset=self.source_dataset)

        if not converted:
            self.dataset.finish_with_error("Could not find any valid items to convert.")
            return

        self.dataset.update_status(f"Finished, converted {converted} items into annotations", is_final=True)
        self.dataset.finish(num_rows=converted)