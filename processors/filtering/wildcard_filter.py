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

    @classmethod
    def get_options(cls, parent_dataset=None, config=None) -> dict:
        """
        Get processor options

        :param parent_dataset DataSet:  An object representing the dataset that
            the processor would be or was run on. Can be used, in conjunction with
            config, to show some options only to privileged users.
        :param config ConfigManager|None config:  Configuration reader (context-aware)
        :return dict:   Options for this processor
        """
        return {
            "match": {
                "type": UserInput.OPTION_TEXT,
                "default": "",
                "help": "Words or phrases to match. You can use * as a wildcard.",
                "tooltip": "Separate with commas."
            }
        }

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Allow processor on NDJSON and CSV files

        :param module: Module to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        """
        return module.is_top_dataset() and module.get_extension() in ("csv", "ndjson")

    def filter_items(self):
        """
        Create a generator to iterate through items that can be passed to create either a csv or ndjson. Use
        `for original_item, mapped_item in self.source_dataset.iterate_mapped_items(self)` to iterate through items
        and yield `original_item`.

        :return generator:
        """

        matches = [match.strip().replace("*", r"[^\s]*") for match in self.parameters.get("match").split(",")]

        # load lexicons from word lists

        matcher = re.compile(r"\b(" + "|".join(matches) + r")\b", flags=re.IGNORECASE)

        # now for the real deal
        self.dataset.update_status("Reading source file")

        # keep some stats
        processed = 0
        matching_items = 0

        # iterate through posts and see if they match
        for mapped_item in self.source_dataset.iterate_items(processor=self):
            processed += 1
            if not mapped_item.get("body", None):
                continue

            if processed % 2500 == 0:
                self.dataset.update_status("Processed %i posts (%i matching)" % (processed, matching_items))
                self.dataset.update_progress(processed / self.source_dataset.num_rows)

            if not matcher.findall(mapped_item.get("body")):
                continue

            matching_items += 1
            yield mapped_item.original
