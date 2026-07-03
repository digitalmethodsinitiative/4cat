"""
Base filter class to handle filetypes
"""
import abc
import csv
import json
import shutil

from backend.lib.processor import BasicProcessor, ProcessorDescription
from common.lib.compatibility import Compatibility
from common.lib.outputs import Filter

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)


class BaseFilter(BasicProcessor):
    """
    Retain only posts where a given column matches a given value
    """
    type = "column-filter"  # job type ID
    description = ProcessorDescription(
        title="Base filter",
        category="Filtering",
        tags=["internal"],
        description="Abstract base class for filters that re-emit a parent dataset's rows. Not runnable on its own.",
        icon="filter",
    )

    item_ids = []

    # A filter re-emits its parent's rows, so its extension, media and columns are
    # the parent's. Subclasses keep this; one that adds a column declares its own.
    output = Filter()

    # Abstract base filter; not runnable on its own (empty type set never matches)
    compatibility = Compatibility(types=set())

    def process(self):
        """
        Reads a file, filtering items that match in the required way, and
        creates a new dataset containing the matching values
        """
        # Get parent extension
        parent_extension = self.source_dataset.get_extension()

        # Filter posts
        matching_items = self.filter_items()

        # Write the posts
        num_posts = 0
        kwargs = {"newline": ""} if parent_extension == "ndjson" else {}

        # Check if we need to copy over annotations
        copy_annotations = True if self.source_dataset.num_annotations() > 0 else False

        zip_file = False
        with self.dataset.get_results_path().open("w", encoding="utf-8", **kwargs) as outfile:

            writer = None
            # Loop through all filtered posts. These ought to be the `original` object in case of a MappedItem; we're
            # filtering, not changing the data (at least in principle).
            for item in matching_items:

                # We're only storing the original items here.
                # We still need the mapped data for annotations.
                item_original = item.original

                # Save the actual item
                if parent_extension == "csv":
                    if not writer:
                        writer = csv.DictWriter(outfile, fieldnames=item_original.keys())
                        writer.writeheader()
                    writer.writerow(item_original)
                elif parent_extension == "ndjson":
                    outfile.write(json.dumps(item_original) + "\n")
                elif parent_extension == "zip":
                    if not zip_file:
                        staging_area = self.dataset.get_staging_area()
                        zip_file = True
                    # copy the file from the source dataset to the new dataset
                    shutil.copy2(item.file, staging_area)
                else:
                    raise NotImplementedError("Parent datasource of type %s cannot be filtered" % parent_extension)

                if copy_annotations:
                    self.item_ids.append(item.get("id", ""))

                num_posts += 1

        if num_posts == 0:
            self.dataset.update_status("No items matched your criteria", is_final=True)

        if self.dataset.is_finished():
            self.dataset.log("Processor already marked dataset as finished prior to saving file!")
            return

        self.dataset.update_label(f"({self.title}) {self.source_dataset.get_label()}")

        # Write the archive if needed and finish the dataset
        if zip_file:
            # check for metadata file and copy it over if it exists
            metadata_file = self.extract_archived_file_by_name(".metadata.json", self.source_dataset.get_results_path())
            if metadata_file:
                shutil.copy2(metadata_file, staging_area)
            self.write_archive_and_finish(staging_area, num_posts)
        else:
            self.dataset.finish(num_posts)

    def after_process(self):
        super().after_process()

        # Request standalone
        self.create_standalone(item_ids=self.item_ids)

    @classmethod
    def is_filter(cls):
        """
        I'm a filter! And so are my children.
        """
        return True

    @abc.abstractmethod
    def filter_items(self):
        """
        Create a generator to iterate through items that can be passed to create either a csv or ndjson. Use
        `for item in self.source_dataset.iterate_items(self)` to iterate through items and access the
        underlying data item via item.original.

        :return generator:
        """
        pass
