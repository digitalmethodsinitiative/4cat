"""
Filter posts by lexicon
"""
import re
import csv

from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)


class WildcardFilter(BasicProcessor):
    """
    Retain only posts matching a given list of keywords
    """
    type = "wildcard-filter"  # job type ID
    category = "Filtering"  # category
    title = "Filter by wildcard"  # title displayed in UI
    description = "Copies the dataset, retaining only posts that match one of a list of phrases that may contain wildcards. This creates a new, separate dataset you can run analyses on."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    # the following determines the options available to the user via the 4CAT
    # interface.
    options = {
        "match": {
            "type": UserInput.OPTION_TEXT,
            "default": "",
            "help": "Keywords to match. You can use * as a wildcard.",
            "tooltip": "Separate with commas."
        }
    }

    def process(self):
        """
        Reads a CSV file, and retains posts matching the provided filter
        """

        matches = [match.strip().replace("*", "[^\s]*") for match in self.parameters.get("match").split(",")]

        # load lexicons from word lists

        matcher = re.compile(r"\b(" + "|".join(matches) + r")\b", flags=re.IGNORECASE)

        # now for the real deal
        self.dataset.update_status("Reading source file")

        # keep some stats
        processed = 0
        matching_items = 0

        with self.dataset.get_results_path().open("w", encoding="utf-8") as output:
            # get header row, we need to copy it for the output
            fieldnames = self.get_item_keys(self.source_file)

            # start the output file
            fieldnames.append("matching_lexicons")
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()

            # iterate through posts and see if they match
            for post in self.iterate_items(self.source_file):
                processed += 1
                if not post.get("body", None):
                    continue

                if processed % 2500 == 0:
                    self.dataset.update_status("Processed %i posts (%i matching)" % (processed, matching_items))

                if not matcher.findall(post.get("body")):
                    continue

                writer.writerow(post)
                matching_items += 1

        self.dataset.update_status("New dataset created with %i matching item(s)" % matching_items, is_final=True)
        self.dataset.finish(matching_items)

    def after_process(self):
        super().after_process()

        # Request standalone
        self.create_standalone()
