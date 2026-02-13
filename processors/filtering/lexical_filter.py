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


class LexicalFilter(BaseFilter):
    """
    Retain only posts matching a given lexicon
    """
    type = "lexical-filter"  # job type ID
    category = "Filtering"  # category
    title = "Filter by words or phrases"  # title displayed in UI
    description = "Retains posts that contain selected words or phrases, including preset word lists. " \
                  "This creates a new dataset."  # description displayed in UI

    references = [
        "[Regex101](https://regex101.com/)"
    ]

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
            "lexicon-custom": {
                "type": UserInput.OPTION_TEXT,
                "default": "",
                "help": "Custom word list (separate with commas)"
            },
            "as_regex": {
                "type": UserInput.OPTION_TOGGLE,
                "default": False,
                "help": "Interpret custom word list as a regular expression",
                "tooltip": "Regular expressions are parsed with Python"
            },
            "exclude": {
                "type": UserInput.OPTION_TOGGLE,
                "default": False,
                "help": "Should not include the above word(s)",
                "tooltip": "Only posts that do not match the above words are retained"
            },
            "case-sensitive": {
                "type": UserInput.OPTION_TOGGLE,
                "default": False,
                "help": "Case sensitive"
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
        exclude = self.parameters.get("exclude", False)
        case_sensitive = self.parameters.get("case-sensitive", False)

        custom_lexicon = self.parameters.get("lexicon-custom", "")
        if not custom_lexicon:
            self.dataset.finish_with_error("No lexicon provided")
            return

        # load lexicons from word lists
        lexicons = {}
        # add user-defined words
        custom_id = "user-defined"
        if custom_id not in lexicons:
            lexicons[custom_id] = set()

        custom_lexicon = set(
            [word.strip() for word in custom_lexicon.split(",") if word.strip()])
        lexicons[custom_id] |= custom_lexicon

        # compile into regex for quick matching
        lexicon_regexes = {}
        for lexicon_id in lexicons:
            if not lexicons[lexicon_id]:
                continue

            if not self.parameters.get("as_regex"):
                phrases = [re.escape(term) for term in lexicons[lexicon_id] if term]
            else:
                phrases = [term for term in lexicons[lexicon_id] if term]

            try:
                if not case_sensitive:
                    lexicon_regexes[lexicon_id] = re.compile(
                        r"\b(" + "|".join(phrases) + r")\b",
                        flags=re.IGNORECASE)
                else:
                    lexicon_regexes[lexicon_id] = re.compile(
                        r"\b(" + "|".join(phrases) + r")\b")
            except re.error:
                self.dataset.finish_with_error("Invalid regular expression, cannot use as filter")
                return

        # now for the real deal
        self.dataset.update_status("Reading source file")
        # keep some stats
        processed = 0
        matching_items = 0
        for mapped_item in self.source_dataset.iterate_items(processor=self):
            if not mapped_item.get("body", None):
                continue

            if processed % 2500 == 0:
                self.dataset.update_status("Processed %i posts (%i matching)" % (processed, matching_items))
                self.dataset.update_progress(processed / self.source_dataset.num_rows)

            # if 'partition' is false, there will just be one combined
            # lexicon, but else we'll have different ones we can
            # check separately
            matching_lexicons = set()
            for lexicon_id in lexicons:
                if lexicon_id not in lexicon_regexes:
                    continue

                lexicon_regex = lexicon_regexes[lexicon_id]

                # check if we match
                if not lexicon_regex.findall(mapped_item["body"]) and not exclude:
                    continue
                elif lexicon_regex.findall(mapped_item["body"]) and exclude:
                    continue

                matching_lexicons.add(lexicon_id)

            # if none of the lexicons match, the post is not retained
            processed += 1
            if not matching_lexicons:
                continue

            # if one does, record which match, and save it to the output
            # TODO: this is a conversion and will not show via map_items() for NDJSONs. Change to annotation!
            mapped_item.original["4cat_matching_lexicons"] = ",".join(matching_lexicons)

            matching_items += 1
            yield mapped_item
