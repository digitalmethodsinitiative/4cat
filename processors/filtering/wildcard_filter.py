"""
Filter posts by lexicon
"""
import re

from processors.filtering.base_filter import BaseFilter
from common.lib.helpers import UserInput

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class WildcardFilter(BaseFilter):
    """
    Retain only posts matching a given list of keywords
    """
    type = "wildcard-filter"  # job type ID
    category = "Filtering"  # category
    title = "Filter by wildcard"  # title displayed in UI
    description = "Retains only posts that contain certain words or phrases. Input may contain a wildcard *, which matches all text in between. This creates a new dataset."  # description displayed in UI

    # the following determines the options available to the user via the 4CAT interface
    options = {
        "match": {
            "type": UserInput.OPTION_TEXT,
            "default": "",
            "help": "Words or phrases to match. You can use * as a wildcard.",
            "tooltip": "Separate with commas."
        }
    }

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow processor on NDJSON and CSV files

        :param module: Module to determine compatibility with
        """
        return module.is_top_dataset() and module.get_extension() in ("csv", "ndjson")

    def filter_items(self):
        """
        Create a generator to iterate through items that can be passed to create either a csv or ndjson. Use
        `for original_item, mapped_item in self.source_dataset.iterate_mapped_items(self)` to iterate through items
        and yield `original_item`.

        :return generator:
        """

        matches = [match.strip().replace("*", "[^\s]*") for match in self.parameters.get("match").split(",")]

        # load lexicons from word lists

        matcher = re.compile(r"\b(" + "|".join(matches) + r")\b", flags=re.IGNORECASE)

        # now for the real deal
        self.dataset.update_status("Reading source file")

        # keep some stats
        processed = 0
        matching_items = 0

        # iterate through posts and see if they match
        for original_item, mapped_item in self.source_dataset.iterate_mapped_items(self):
            processed += 1
            if not mapped_item.get("body", None):
                continue

            if processed % 2500 == 0:
                self.dataset.update_status("Processed %i posts (%i matching)" % (processed, matching_items))
                self.dataset.update_progress(processed / self.source_dataset.num_rows)

            if not matcher.findall(mapped_item.get("body")):
                continue

            matching_items += 1
            yield original_item
