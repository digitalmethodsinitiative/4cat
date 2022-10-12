"""
Base filter class to handle filetypes
"""
import abc
import csv
import json

from backend.abstract.processor import BasicProcessor

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
    def is_compatible_with(cls, module=None):
        """
        This is meant to be inherited by other child classes

        :param module: Dataset or processor to determine compatibility with
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
        if matching_posts is None:
            self.dataset.update_status("No results matched filter", is_final=True)
            if self.dataset.is_finished():
                return
            else:
                self.dataset.finish(0)
                return

        # Write the posts
        num_posts = 0
        if parent_extension == "csv":
            with self.dataset.get_results_path().open("w", encoding="utf-8") as outfile:
                writer = None
                for post in matching_posts:
                    if not writer:
                        writer = csv.DictWriter(outfile, fieldnames=post.keys())
                        writer.writeheader()
                    writer.writerow(post)
                    num_posts += 1
        elif parent_extension == "ndjson":
            with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile:
                for post in matching_posts:

                    outfile.write(json.dumps(post) + "\n")
                    num_posts += 1
        else:
            raise NotImplementedError("Parent datasource of type %s cannot be filtered" % parent_extension)

        if num_posts == 0:
            self.dataset.update_status("No items matched your criteria", is_final=True)

        self.dataset.finish(num_posts)

    def after_process(self):
        super().after_process()

        # Request standalone
        self.create_standalone()

    @abc.abstractmethod
    def filter_items(self):
        """
        Create a generator to iterate through items that can be passed to create either a csv or ndjson. Use
        `for original_item, mapped_item in self.source_dataset.iterate_mapped_items(self)` to iterate through items
        and yield `original_item`.

        :return generator:
        """
        pass
