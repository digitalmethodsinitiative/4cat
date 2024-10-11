"""
Filter posts by lexicon
"""
import re
from pathlib import Path
import spacy

from processors.filtering.base_filter import BaseFilter
from common.lib.helpers import UserInput
from common.config_manager import config


__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class LexicalFilter(BaseFilter):
    """
    Retain only posts matching a given lexicon
    """
    type = "lexical-filter-lemma-spacy-fin"  # job type ID
    category = "Filtering"  # category
    title = "Filter by words or phrases in Finnish using  spacy lemmatization"  # title displayed in UI
    description = "Retains posts that contain selected words or phrases. It matches word lemmas.  " \
                  "This creates a new dataset."  # description displayed in UI

    references = [
        "[spacy](https://spacy.io/)"
    ]

    # the following determines the options available to the user via the 4CAT
    # interface.
    options = {
        "lexicon-custom": {
            "type": UserInput.OPTION_TEXT,
            "default": "",
            "help": "Custom word list (separate with commas)"
        },
        "exclude": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Should not include the above word(s)",
            "tooltip": "Only posts that do not match the above words are retained"
        }
    }

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow processor on NDJSON and CSV files

        :param module: Module to determine compatibility with
        """
        return module.is_top_dataset() and module.get_extension() in ("csv", "ndjson") and module.language == 'fi'

    def filter_items(self):
        """
        Create a generator to iterate through items that can be passed to create either a csv or ndjson. Use
        `for original_item, mapped_item in self.source_dataset.iterate_mapped_items(self)` to iterate through items
        and yield `original_item`.

        :return generator:
        """
        exclude = self.parameters.get("exclude", False)
        
        #lemmatize the wordlist
        lexicon_words = self.parameters.get("lexicon-custom", "")
        lexicon_words = lexicon_words.replace(",", " ")


        nlp = spacy.load("fi_core_news_sm", disable=['parser', 'ner'])

        tokens = nlp(lexicon_words)
        lemmas = [token.lemma_ for token in tokens]



        lexicon_regexes = re.compile(
                        r"\b(" + "|".join(lemmas) + r")\b")
        
       

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
            matching_lexicons = False
            
            #lemmatize the body text
            tokens = nlp(mapped_item["body"])
            body_lemmas_list = [token.lemma_ for token in tokens]
            body_lemmas = " ".join(body_lemmas_list)

            # check if we match
            if not lexicon_regexes.findall(body_lemmas) and not exclude:
                continue
            elif lexicon_regexes.findall(body_lemmas) and exclude:
                continue

            matching_lexicons = True

            # if none of the lexicons match, the post is not retained
            processed += 1
            if not matching_lexicons:
                continue

            # if one does, record which match, and save it to the output
            # TODO: this is a conversion and will not show via map_items() for NDJSONs
            #mapped_item.original["4cat_matching_lexicons"] = ",".join(matching_lexicons)

            matching_items += 1
            yield mapped_item.original
