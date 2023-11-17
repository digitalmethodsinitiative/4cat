"""
Merge one dataset with another (creating a new dataset)
"""
import csv
import json

from backend.lib.processor import BasicProcessor
from common.lib.dataset import DataSet
from common.lib.exceptions import ProcessorInterruptedException, DataSetException
from common.lib.helpers import UserInput
import ural

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)


class DatasetMerger(BasicProcessor):
    """
    Merge two datasets
    """
    type = "merge-datasets"  # job type ID
    category = "Conversion"  # category
    title = "Merge datasets"  # title displayed in UI
    description = "Merge this dataset with other datasets of the same format. A new dataset is " \
                  "created containing a combination of items from the original datasets."  # description displayed in UI

    options = {
        "source": {
            "type": UserInput.OPTION_TEXT_LARGE,
            "help": "Source dataset URLs",
            "tooltip": "This should be the URL(s) of the result pages of the 4CAT dataset you want to merge with this "
                       "dataset. Note that all datasets need to have the same format! Separate URLs with new lines or "
                       "commas."
        },
        "merge": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Merge strategy",
            "options": {
                "remove": "Remove duplicates",
                "keep": "Keep duplicates"
            },
            "tooltip": "What to do with items that occur in both datasets? Items are considered duplicate if their ID "
                       "is identical, regardless of the value of other properties",
            "default": "remove"
        }
    }

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow processor on any top-level CSV or NDJSON file

        :param module: Module to determine compatibility with
        """
        return module.get_extension() in ("csv", "ndjson") and (module.is_from_collector())

    @staticmethod
    def get_dataset_from_url(url, db):
        """
        Get dataset object based on dataset URL

        Uses the last part of the URL path as the Dataset ID

        :param str url:  Dataset URL
        :param db:  Database handler (to retrieve metadata)
        :return DataSet:  The dataset
        """
        source_url = ural.normalize_url(url)
        source_key = source_url.split("/")[-1]
        return DataSet(key=source_key, db=db)

    def process(self):
        """
        This merges two datasets into a new, combined dataset

        This is trickier than it sounds! First we need to make sure that the
        datasets are compatible, and then we need to figure out what to do with
        any duplicates.
        """
        source_datasets = [self.source_dataset]
        total_items = self.source_dataset.num_rows
        for source_dataset in self.parameters.get("source").replace("\n", ",").split(","):
            source_dataset_url = source_dataset.strip()
            try:
                source_dataset = self.get_dataset_from_url(source_dataset_url, self.db)
            except DataSetException:
                return self.dataset.finish_with_error(f"Dataset URL '{source_dataset_url} not found - cannot perform "
                                                      f"merge.")

            if not source_dataset.is_finished():
                return self.dataset.finish_with_error(f"Dataset with URL {source_dataset_url} is unfinished - finish "
                                                      f"datasets before merging.")

            #if source_dataset.type != self.source_dataset.type:
            #    return self.dataset.finish_with_error(f"Dataset with URL {source_dataset_url} is not of the right "
            #                                          f"type - all datasets must be of the type "
            #                                          f"'{self.source_dataset.type}")

            if not set(source_dataset.get_owners_users("owner")).intersection(
                    set(self.source_dataset.get_owners_users("owner"))) and (
                    source_dataset.is_private or self.source_dataset.is_private):
                return self.dataset.finish_with_error("Cannot merge datasets - all need to be public or have "
                                                      "overlapping ownership.")

            if source_dataset.key in [d.key for d in source_datasets]:
                self.dataset.update_status(f"Skipping dataset with URL {source_dataset_url} - already in list of "
                                           f"datasets to merge")
            else:
                total_items += source_dataset.num_rows
                source_datasets.append(source_dataset)

        # clean up parameters
        self.dataset.parameters = {**self.dataset.parameters, "source": ", ".join([d.key for d in source_datasets])}

        # ok, now we know that the datasets are actually compatible and can be
        # merged
        processed = 0
        duplicates = 0
        merged = 0
        canonical_fieldnames = None
        sorted_canonical_fieldnames = None
        writer = None

        # find potential duplicates and check if columns are compatible (if
        # merging csvs)
        seen_ids = set()
        with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile:
            for dataset in source_datasets:
                for original_item, mapped_item in dataset.iterate_mapped_items():
                    if self.interrupted:
                        raise ProcessorInterruptedException("Interrupted while mapping duplicates")

                    if not canonical_fieldnames:
                        canonical_fieldnames = set(mapped_item.keys())
                        sorted_canonical_fieldnames = list(mapped_item.keys())
                    else:
                        item_fieldnames = set(mapped_item.keys())
                        if item_fieldnames != canonical_fieldnames:
                            return self.dataset.finish_with_error("Cannot merge datasets - not the same set of "
                                                                  "attributes per item (are they not the same type or "
                                                                  "has one been altered by a processor?)")

                    processed += 1
                    if self.parameters["merge"] != "keep" and mapped_item.get("id") in seen_ids:
                        duplicates += 1
                        continue

                    seen_ids.add(mapped_item.get("id"))
                    merged += 1

                    if dataset.get_extension() == "csv":
                        if not writer:
                            writer = csv.DictWriter(outfile, fieldnames=sorted_canonical_fieldnames)
                            writer.writeheader()

                        writer.writerow(original_item)

                    elif dataset.get_extension() == "ndjson":
                        outfile.write(json.dumps(original_item) + "\n")

                    self.update_progress(processed, total_items)

        # phew, finally done
        self.dataset.update_status(f"Merged {processed:,} items ({merged:,} merged, {duplicates:,} skipped)",
                                   is_final=True)
        self.dataset.update_progress(1)

        self.dataset.finish(processed)

    def update_progress(self, processed, total, force=False):
        """
        Convenience function because in this processor the update is called in a couple of places

        :param int processed:  Items processed so far
        :param int total:  Total items
        :param bool force:  Force an update
        :return:
        """
        if processed % 100 == 0 or force:
            self.dataset.update_status("Merged %s of %s items" % ("{:,}".format(processed), "{:,}".format(total)),
                                       is_final=force)
            if total != 0:
                self.dataset.update_progress(processed / total)

    @classmethod
    def is_filter(cls):
        """
        Is this processor a filter?

        Yes it is!

        :return bool:  Always True
        """
        return True

    def after_process(self):
        """
        Create stand-alone dataset with merged data

        :return:
        """
        super().after_process()

        # Request standalone
        standalone = self.create_standalone()
        if not standalone:
            # something failed earlier, so there's nothing to copy or make
            # standalone
            return

        # merged dataset has the same type as the original
        if self.source_dataset.parameters.get("datasource"):
            standalone.change_datasource(self.source_dataset.parameters["datasource"])

        standalone.parameters = {**self.dataset.parameters, "board": "merged"}
        standalone.type = self.source_dataset.type
