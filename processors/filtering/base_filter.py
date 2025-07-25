"""
Base filter class to handle filetypes
"""
import abc
import csv
import json

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

        # If this source dataset has less than n annotations, just retrieve them all before iterating
        
        # Write the posts
        num_posts = 0
        kwargs = {"newline": ""} if parent_extension == "ndjson" else {}

        with self.dataset.get_results_path().open("w", encoding="utf-8", **kwargs) as outfile:

            writer = None
            # Loop through all filtered posts. These ought to be the `original` object in case of a MappedItem; we're
            # filtering, not changing the data (at least in principle).
            for post in matching_posts:

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

                num_posts += 1

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
