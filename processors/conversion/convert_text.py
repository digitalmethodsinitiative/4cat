"""
Change the text in a dataset and write it to a new one
"""
import re
import csv

from common.lib.exceptions import ProcessorInterruptedException
from backend.lib.processor import BasicProcessor
from common.lib.helpers import UserInput

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


class ConvertText(BasicProcessor):
    """
    Retain only posts matching a given lexicon
    """
    type = "convert-text"  # job type ID
    category = "Conversion"  # category
    title = "Convert text"  # title displayed in UI
    description = ("Changes text and outputs these in a new dataset. Converted text can also be added to the original "
                   "dataset as annotations.")  # description displayed in UI
    extension = "csv"

    @classmethod
    def get_options(cls, parent_dataset=None, config=None) -> dict:

        options = {
            "columns": {
                "type": UserInput.OPTION_TEXT,
                "default": "body",
                "help": "Columns with texts to replace",
            },
            "find": {
                "type": UserInput.OPTION_TEXT,
                "default": "",
                "help": "Text to replace",
                "tooltip": "Multiple values can be replaced, separate with comma.",
            },
            "as_regex": {
                "type": UserInput.OPTION_TOGGLE,
                "default": False,
                "help": "Interpret text to replace as regular expression",
                "tooltip": "Regular expressions are parsed with Python",
            },
            "replace": {
                "type": UserInput.OPTION_TEXT,
                "default": "",
                "help": "Text to insert",
                "tooltip": "This can only be a single string value. Whitespace characters will also be inserted.",
            },
            "whitespace-notice": {
                "type": UserInput.OPTION_INFO,
                "help": "Note: whitespace characters are taken into account. Using 'cat, dog' as text to replace will "
                "match all occurrences of 'cat' but only ' dog', starting with a whitespace. This also goes "
                "for replacement text: replacing 'cat' with ' cat ' will add whitespaces.",
            },
            "case-sensitive": {
                "type": UserInput.OPTION_TOGGLE,
                "default": False,
                "help": "Case sensitive",
            },
            "save_annotations": {
                "type": UserInput.OPTION_ANNOTATION,
                "label": "converted text",
                "tooltip": "The converted text will be added as a new column to the previous dataset",
                "default": False,
                "to_parent": True
            }
        }

        # Get the columns for the select columns option
        if parent_dataset and parent_dataset.get_columns():
            columns = parent_dataset.get_columns()
            options["columns"]["type"] = UserInput.OPTION_MULTI
            options["columns"]["inline"] = True
            options["columns"]["options"] = {v: v for v in columns}
            options["columns"]["default"] = "body" if "body" in columns else sorted(columns,
                                                                                    key=lambda
                                                                                        k: "text" in k).pop()
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
        Create a generator to iterate through items that can be passed to create either a csv or ndjson.

        :return generator:
        """

        # Get column parameters
        columns = self.parameters.get("columns", [])
        if isinstance(columns, str):
            columns = [columns]

        find = self.parameters.get("find", "")
        if not find:
            self.dataset.finish_with_error("Please indicate what text should be replaced")
            return

        replace = self.parameters.get("replace", "").replace("\\", r"\\")
        if not replace:
            self.dataset.finish_with_error("Please provide a replacement text")
            return

        case_sensitive = self.parameters.get("case-sensitive", False)
        kwargs = {}
        if not case_sensitive:
            kwargs["flags"] = re.IGNORECASE
        as_regex = self.parameters.get("as_regex")
        if not as_regex:
            find = [re.escape(term) for term in find.split(",")]
        try:
            if not as_regex:
                regex = re.compile(r"(" + "|".join(find) + r")", **kwargs)
            else:
                regex = re.compile(fr"{find}", **kwargs)
        except re.error:
            self.dataset.finish_with_error("Invalid regular expression, cannot use as filter")
            return

        save_annotations = self.parameters.get("save_annotations")

        # now for the real deal
        self.dataset.update_status("Reading source file")
        # keep some stats
        processed = 0
        replaced_total = 0

        annotations = []

        with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as output:

            fieldnames = ["id"] + columns + ["replacements"]
            writer = csv.DictWriter(output, fieldnames=fieldnames)

            for item in self.source_dataset.iterate_items():
                if self.interrupted:
                    raise ProcessorInterruptedException(
                        "Interrupted while replacing texts"
                    )

                converted_item = {"id": item["id"] if "id" in item else processed + 1}
                replaced = 0

                # Convert text in every column
                for column in columns:

                    converted_item[column] = item[column]

                    try:
                        item_value = str(item[column])
                    except ValueError:
                        self.dataset.update_status(f"Could not convert {column} item in row {processed} to a string")
                        continue

                    # check if there's anything to replace
                    replace_value, n_replaced = regex.subn(replace, item_value)

                    if n_replaced > 0:
                        # Store converted text
                        converted_item[column] = replace_value
                        replaced += n_replaced

                        # Save replaced value as annotation?
                        # Not top parent this time; text conversion can be used with any csv or ndjson
                        if save_annotations:
                            # Annotations need item ids though
                            if not item.get("id"):
                                save_annotations = False
                                self.dataset.update_status(
                                    "Could not save converted text to parent dataset because it "
                                    "has no id column"
                                )
                                continue

                            annotation = {
                                "item_id": item["id"],
                                "label": column + "_replaced",
                                "value": replace_value,
                            }
                            annotations.append(annotation)

                if processed == 0:  # Write header on first row
                    writer.writeheader()

                converted_item["replacements"] = replaced
                writer.writerow(converted_item)
                processed += 1
                replaced_total += replaced

                if processed % 2500 == 0:
                    if save_annotations:
                        self.save_annotations(annotations, source_dataset=self.source_dataset)
                    annotations = []
                    self.dataset.update_status(
                        f"Made {replaced_total} text changes in {processed} rows"
                    )
                    self.dataset.update_progress(
                        processed / self.source_dataset.num_rows
                    )

        # Write leftover annotations
        if annotations:
            self.save_annotations(annotations, source_dataset=self.source_dataset)

        self.dataset.update_status(f"Finished, changed {replaced_total} texts in {processed} rows", is_final=True)
        self.dataset.finish(num_rows=processed)