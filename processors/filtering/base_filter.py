"""
Base filter class to handle filetypes
"""
import abc
import csv
import json
import secrets
import collections

from common.lib.item_mapping import MappedItem
from common.lib.helpers import hash_to_md5
from backend.lib.processor import BasicProcessor

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
    category = "Filtering"  # category
    title = "Base Filter"  # title displayed in UI
    description = "This should not be available."

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        This is meant to be inherited by other child classes

        :param module: Module to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        """
        return False

    def process(self):
        """
        Reads a file, filtering items that match in the required way, and
        creates a new dataset containing the matching values
        """
        # Get parent extension
        parent_extension = self.source_dataset.get_extension()

        # Filter posts
        matching_posts = self.filter_items()

        # Keep track of whether we need to copy over annotations and/or annotation fields
        annotation_fields = self.source_dataset.annotation_fields
        num_annotations = 0 if not annotation_fields else self.source_dataset.num_annotations()
        all_annotations = None

        # If this source dataset has less than n annotations, just retrieve them all before iterating
        if 0 < num_annotations <= 500:
            # Convert to dict for faster lookup when iterating over items
            all_annotations = collections.defaultdict(list)
            for annotation in self.source_dataset.get_annotations():
                all_annotations[annotation.item_id].append(annotation)

        # Write the posts
        num_posts = 0
        kwargs = {"newline": ""} if parent_extension == "ndjson" else {}

        with self.dataset.get_results_path().open("w", encoding="utf-8", **kwargs) as outfile:

            writer = None
            copied_annotations = []

            # Loop through all filtered posts. These ought to be the `original` object in case of a MappedItem; we're
            # filtering, not changing the data (at least in principle).
            for post in matching_posts:

                # If the original dataset has annotations, we'll copy these over to the filtered dataset.
                if annotation_fields:
                    # For small datasets, get the annotations from all this dataset's annotations
                    if all_annotations:
                        item_annotations = all_annotations.get(post["id"])
                    # Or get annotations per item for large datasets (more queries but less memory usage)
                    else:
                        item_annotations = self.source_dataset.get_annotations_for_item(
                            post["id"]
                        )

                    if item_annotations:
                        # Only use the annotation data to instantiate a new Annotation object, with a fresh ID
                        item_annotations = [item_annotation.data for item_annotation in item_annotations]

                        # Change some annotation values
                        for i in range(len(item_annotations)):
                            del item_annotations[i]["id"]  #  Set by the db
                            item_annotations[i]["dataset"] = self.dataset.key  # Changed in `get_standalone()`
                        copied_annotations += item_annotations

                # Save the actual item
                if parent_extension == "csv":
                    if not writer:
                        writer = csv.DictWriter(outfile, fieldnames=post.keys())
                        writer.writeheader()
                    writer.writerow(post)
                elif parent_extension == "ndjson":
                    outfile.write(json.dumps(post) + "\n")
                else:
                    raise NotImplementedError("Parent datasource of type %s cannot be filtered" % parent_extension)

                # copy annotations in bulk
                if len(copied_annotations) > 1000:
                    self.dataset.save_annotations(copied_annotations)
                    copied_annotations = []

                num_posts += 1

        # copy over leftover annotations
        # annotation fields are copied over in `create_standalone()`
        if copied_annotations:
            self.dataset.save_annotations(copied_annotations)

        if num_posts == 0:
            self.dataset.update_status("No items matched your criteria", is_final=True)

        if self.dataset.is_finished():
            self.dataset.log("Processor already marked dataset as finished prior to saving file!")
            return

        self.dataset.update_label(f"({self.title}) {self.source_dataset.get_label()}")
        self.dataset.finish(num_posts)

    def after_process(self):
        super().after_process()

        # Request standalone
        self.create_standalone()

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
