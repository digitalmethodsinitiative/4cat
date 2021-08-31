"""
Blank all columns containing author information
"""
import shutil
import copy
import json
import csv
import re

from backend.abstract.processor import BasicProcessor
from common.lib.helpers import dict_search_and_update

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
    title = "Remove author information"  # title displayed in UI
    description = "Anonymises a dataset by removing content of any column starting with 'author'"
    extension = "csv"  # extension of result file, used internally and in UI

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Allow processor on CSV files

        :param module: Dataset or processor to determine compatibility with
        """
        return module.is_top_dataset() and module.get_extension() in ["csv", 'ndjson']

    def process(self):
        """
        Reads a CSV file, removing content from all columns starting with "author"
        """

        with self.dataset.get_results_path().open("w", encoding="utf-8") as outfile:
            processed_items = 0

            if self.source_file.suffix.lower() == ".csv":
                writer = None
                author_columns = []

                for item in self.iterate_items(self.source_file):
                    if not writer:
                        # initialise csv writer - we do this explicitly rather than
                        # using self.write_items_and_finish() because else we have
                        # to store a potentially very large amount of items in
                        # memory which is not a good idea
                        writer = csv.DictWriter(outfile, fieldnames=item.keys())
                        author_columns = [field for field in item.keys() if re.match(r"author.*", field)]
                        writer.writeheader()

                    processed_items += 1
                    if processed_items % 500 == 0:
                        self.dataset.update_status("Processed %i items" % processed_items)

                    for field in author_columns:
                        item[field] = ""

                    writer.writerow(item)

            elif self.source_file.suffix.lower() == ".ndjson":
                # Iterating through items
                # using bypass_map_item to not modify data further than necessary
                for item in self.iterate_items(self.source_file, bypass_map_item=True):
                    # Delete author data
                    item = dict_search_and_update(item, ['author'], lambda x: 'REDACTED')

                    # Write modified item
                    outfile.write(json.dumps(item, ensure_ascii=False))
                    # Add newline for NDJSON file
                    outfile.write('\n')

                    # Update status
                    processed_items += 1
                    if processed_items % 500 == 0:
                        self.dataset.update_status("Processed %i items" % processed_items)
            else:
                raise NotImplementedError("Cannot iterate through %s file" % self.source_file.suffix)

        # replace original dataset with updated one
        shutil.move(self.dataset.get_results_path(), self.source_dataset.get_results_path())

        self.dataset.update_status("Dataset updated.", is_final=True)
        self.dataset.finish(processed_items)
