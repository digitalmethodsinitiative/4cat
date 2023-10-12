"""
Blank all columns containing author information
"""
import fnmatch
import hashlib
import secrets
import shutil
import json
import csv

from backend.lib.processor import BasicProcessor
from common.lib.helpers import dict_search_and_update, UserInput, HashCache

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)


class AuthorInfoRemover(BasicProcessor):
    """
    Retain only posts where a given column matches a given value
    """
    type = "author-info-remover"  # job type ID
    category = "Filtering"  # category
    title = "Pseudonymise or anonymise"  # title displayed in UI
    description = "Removes or replaces data from the dataset in fields identified as containing personal information"

    references = [
        "[What is a hash?](https://techterms.com/definition/hash)",
        "[What is a salt?](https://en.wikipedia.org/wiki/Salt_(cryptography))",
        "[What is Blake2?](https://en.wikipedia.org/wiki/BLAKE_(hash_function)#BLAKE2)"
    ]

    options = {
        "mode": {
            "help": "Filtering mode",
            "type": UserInput.OPTION_CHOICE,
            "options": {
                "anonymise": "Replace values with 'REDACTED'",
                "pseudonymise": "Replace values with a salted hash"
            },
            "tooltip": "When replacing values with a hash, a Blake2b hash is calculated for the value with a "
                       "randomised salt, so it is no longer possible to derive the original value from the hash but it "
                       "remains possible to see if two fields contain the same value.",
            "default": "anonymise"
        },
        "fields": {
            "help": "Fields to update",
            "type": UserInput.OPTION_TEXT,
            "tooltip": "Separate with commas. You can use wildcards (e.g. 'author_*').",
            "default": "author*,user*"
        }
    }

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow processor on CSV files

        :param module: Module to determine compatibility with
        """
        return module.is_top_dataset() and module.get_extension() in ["csv", 'ndjson']

    def process(self):
        """
        Reads a CSV file, removing content from all columns starting with "author"
        """
        # hasher for pseudonymisation
        salt = secrets.token_bytes(16)
        hasher = hashlib.blake2b(digest_size=24, salt=salt)
        hash_cache = HashCache(hasher)

        mode = self.parameters.get("mode")
        fields = self.parameters.get("fields")
        if type(fields) is str:
            fields = [field.strip() for field in fields.split(",")]

        with self.dataset.get_results_path().open("w", encoding="utf-8") as outfile:
            processed_items = 0

            if self.source_file.suffix.lower() == ".csv":
                writer = None
                filterable_fields = []

                for item in self.source_dataset.iterate_items(self):
                    if not writer:
                        # initialise csv writer - we do this explicitly rather than
                        # using self.write_items_and_finish() because else we have
                        # to store a potentially very large amount of items in
                        # memory which is not a good idea
                        writer = csv.DictWriter(outfile, fieldnames=item.keys())
                        writer.writeheader()

                        # figure out which fields to filter (same for every item)
                        for field in item.keys():
                            if any([fnmatch.fnmatch(field, pattern) for pattern in fields]):
                                filterable_fields.append(field)

                    processed_items += 1
                    if processed_items % 500 == 0:
                        self.dataset.update_status(f"Processed {processed_items:,} of "
                                                   f"{self.source_dataset.num_rows:,} items")
                        self.dataset.update_progress(processed_items / self.source_dataset.num_rows)

                    for field in filterable_fields:
                        if mode == "anonymise":
                            item[field] = "REDACTED"
                        elif mode == "pseudonymise":
                            item[field] = hash_cache.update_cache(item[field])

                    writer.writerow(item)

            elif self.source_file.suffix.lower() == ".ndjson":
                # Iterating through items
                # using bypass_map_item to not modify data further than necessary
                for item in self.source_dataset.iterate_items(self, bypass_map_item=True):
                    # Filter author data
                    if mode == "anonymise":
                        item = dict_search_and_update(item, fields, lambda v: "REDACTED")
                    else:
                        item = dict_search_and_update(item, fields, hash_cache.update_cache)

                    # Write modified item
                    outfile.write(json.dumps(item, ensure_ascii=False) + "\n")

                    # Update status
                    processed_items += 1
                    if processed_items % 500 == 0:
                        self.dataset.update_status(f"Processed {processed_items:,} of "
                                                   f"{self.source_dataset.num_rows:,} items")
                        self.dataset.update_progress(processed_items / self.source_dataset.num_rows)
            else:
                raise NotImplementedError(f"Cannot iterate through {self.source_file.suffix} file")

        # replace original dataset with updated one
        shutil.move(self.dataset.get_results_path(), self.source_dataset.get_results_path())

        self.dataset.update_status("Data filtered, parent dataset updated.", is_final=True)
        self.dataset.finish(processed_items)

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        Get processor options

        These are dynamic for this processor: the 'column names' option is
        populated with the column names from the parent dataset, if available.

        :param DataSet parent_dataset:  Parent dataset
        :param user:  Flask User to which the options are shown, if applicable
        :return dict:  Processor options
        """
        options = cls.options
        if parent_dataset is None:
            return options

        parent_columns = parent_dataset.get_columns()

        if parent_dataset.get_extension() == "csv":
            parent_columns = {c: c for c in sorted(parent_columns)}
            defaults = [c for c in parent_columns if c.startswith("author")]
            options["fields"] = {
                "type": UserInput.OPTION_MULTI_SELECT,
                "options": parent_columns,
                "help": "Columns to process",
                "default": defaults,
                "tooltip": "Values in these columns will be replaced"
            }

        return options
