"""
Merge one dataset with another (creating a new dataset)
"""
import csv
import json

from backend.abstract.processor import BasicProcessor
from common.lib.dataset import DataSet
from common.lib.exceptions import ProcessorInterruptedException
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
    description = "Merge this dataset with another dataset of the same type. A new, third dataset is " \
                  "created containing items from both original datasets."  # description displayed in UI

    options = {
        "source": {
            "type": UserInput.OPTION_TEXT,
            "help": "Source dataset URL",
            "tooltip": "This should be the URL of the result page of the 4CAT dataset you want to merge with this "
                       "dataset. Note that both datasets need to be of the same type!"
        },
        "merge": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Merge strategy",
            "options": {
                "remove": "Remove duplicates",
                "keep": "Keep duplicates",
                "commas": "Merge duplicates, combine different column values into a list"
            },
            "tooltip": "What to do with items that occur in both datasets? Items are considered duplicate if their ID "
                       "is identical, regardless of the value of other properties",
            "default": "remove"
        }
    }

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Allow processor on iterable files

        :param module: Dataset or processor to determine compatibility with
        """
        return module.get_extension() in ("csv", "ndjson")

    @staticmethod
    def get_dataset_from_url(url, db):
        """
        Get dataset object based on dataset URL

        Uses the last part of the URL path as the Datset ID

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
        datasets are compatible and then we need to figure out what to do with
        any duplicates.
        """
        try:
            first_dataset = self.get_dataset_from_url(self.parameters.get("source"), self.db)
        except TypeError:
            return self.dataset.finish_with_error("Dataset URL invalid - cannot perform merge.")

        if not first_dataset.is_finished():
            return self.dataset.finish_with_error("Cannot merge datasets - source dataset is not finished yet.")

        second_dataset = self.source_dataset

        # this checks extension rather than processor type, because two
        # processors may still produce datasets with the same format
        if first_dataset.type != second_dataset.type or \
                first_dataset.get_extension() != second_dataset.get_extension():
            return self.dataset.finish_with_error("Cannot merge datasets - they need to be of the same type.")

        # even admins cannot merge private datasets with public datasets - but
        # they can of course make a private dataset public
        if first_dataset.owner != second_dataset.owner and (first_dataset.is_private or second_dataset.is_private):
            return self.dataset.finish_with_error("Cannot merge datasets - both need to be public or have the same "
                                                  "owner.")

        # ok, now we know that the datasets are actually compatible and can be
        # merged
        total_items = first_dataset.num_rows + second_dataset.num_rows
        processed_items = 0
        duplicates = {}
        first_fieldnames = {}
        first_processor = first_dataset.get_own_processor()
        second_processor = second_dataset.get_own_processor()

        # find potential duplicates and check if columns are compatible (if
        # merging csvs)
        if self.parameters["merge"] != "keep":
            for first_item in first_dataset.iterate_items(bypass_map_item=True):
                first_fieldnames = set(first_item.keys())
                for second_item in second_dataset.iterate_items(bypass_map_item=True):
                    if self.interrupted:
                        raise ProcessorInterruptedException("Interrupted while mapping duplicates")

                    second_fieldnames = set(second_item.keys())
                    if first_dataset.get_extension() == "csv" and first_fieldnames != second_fieldnames:
                        return self.dataset.finish_with_error(
                            "Cannot merge datasets - not the same columns (has one been altered by a processor?)")

                    first_id = first_item.get("item_id", first_processor.map_item(first_item)["item_id"])
                    second_id = second_item.get("item_id", second_processor.map_item(second_item)["item_id"])
                    if first_id != second_id:
                        continue

                    duplicates[first_id] = second_item
                    if self.parameters["merge"] in ("commas", "remove"):
                        total_items -= 1

        # have duplicates been detected?
        dupe_msg = ""
        if duplicates:
            dupe_msg = " (%s duplicate%s)" % ("{:,}".format(len(duplicates)), "s" if len(duplicates) != 1 else "")
            self.dataset.update_status("%s duplicate items were found. Using the '%s' strategy for duplicates." %
                                       ("{:,}".format(len(duplicates)), self.parameters.get("merge")))

        # actually merge the datasets finally!! we need a separate strategy for
        # each file format
        with self.dataset.get_results_path().open("w", encoding="utf-8", newline="\n") as outfile:
            # csv files
            if first_dataset.get_extension() == "csv":
                writer = csv.DictWriter(outfile, fieldnames=first_fieldnames)
                writer.writeheader()

                # from the first dataset, all items can be copied
                for item in first_dataset.iterate_items():
                    if self.interrupted:
                        raise ProcessorInterruptedException("Interrupted while merging file 1")

                    if item["item_id"] in duplicates and self.parameters["merge"] == "commas":
                        for field, value in duplicates["item_id"].items():
                            # comma-separated list if values are different
                            if value != item[field]:
                                item[field] += "," + value

                    writer.writerow(item)
                    processed_items += 1
                    self.update_progress(processed_items, total_items)

                # from the second also, unless they are dupes
                for item in second_dataset.iterate_items():
                    if self.interrupted:
                        raise ProcessorInterruptedException("Interrupted while merging file 2")

                    self.update_progress(processed_items, total_items)
                    if item["item_id"] in duplicates:
                        if self.parameters["merge"] in ("commas", "remove"):
                            continue
                        elif self.parameters["merge"] == "keep":
                            writer.writerow(item)
                            processed_items += 1

            # ndjson files
            elif first_dataset.get_extension() == "ndjson":

                # again, for the first all items can be written
                for item in first_dataset.iterate_items(bypass_map_item=True):
                    if self.interrupted:
                        raise ProcessorInterruptedException("Interrupted while merging file 1")

                    first_id = first_processor.map_item(item)["item_id"]

                    if first_id in duplicates and self.parameters.get("merge") == "commas":
                        for field, value in duplicates[first_id].items():
                            # comma-separated if scalar, else a json list
                            if field not in item:
                                item[field] = value
                            elif item[field] != value:
                                if type(item[field]) in (str, int, float):
                                    item[field] = str(item[field]) + "," + str(value)
                                else:
                                    item[field] = [item[field], value]

                    outfile.write(json.dumps(item) + "\n")
                    processed_items += 1
                    self.update_progress(processed_items, total_items)

                # for the second, merging is potentially in order
                for item in second_dataset.iterate_items(bypass_map_item=True):
                    if self.interrupted:
                        raise ProcessorInterruptedException("Interrupted while merging file 2")

                    second_id = second_processor.map_item(item)["item_id"]
                    self.update_progress(processed_items, total_items)
                    if second_id in duplicates and self.parameters.get("merge") in ("remove", "commas"):
                        continue

                    processed_items += 1
                    outfile.write(json.dumps(item) + "\n")

        # phew, finally done
        self.dataset.update_status("Merged %s items.%s" % ("{:,}".format(processed_items), dupe_msg), is_final=True)
        self.dataset.update_progress(1)
        self.dataset.finish(processed_items)

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
        self.create_standalone()
