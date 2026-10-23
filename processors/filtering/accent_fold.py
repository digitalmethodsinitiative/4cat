"""
Fold accents, case, and diacritics.
"""
import unicodedata
import csv

from unidecode import unidecode
from backend.lib.processor import BasicProcessor
from common.lib.compatibility import Compatibility
from common.lib.helpers import UserInput

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)


class AccentFoldingFilter(BasicProcessor):
    """
    Fold accents, case, and diacritics.
    """
    type = "accent-folder"  # job type ID
    category = "Filtering"  # category
    title = "Convert accented and non-Latin characters"  # title displayed in UI
    description = ("Makes words that are written with and without accents count as the same word, e.g. 'canción' and "
                   "'cancion'. It can also rewrite all text in Latin letters. This creates a new dataset.")
    extension = "csv"  # extension of result file, used internally and in UI

    # Allow on top-level CSV datasets
    compatibility = Compatibility(top_dataset_only=True, extensions={"csv"})

    # scripts from which accents are removed. The Unicode names of their
    # letters contain these words, e.g. 'GREEK SMALL LETTER ALPHA'
    FOLDED_SCRIPTS = {"LATIN", "GREEK", "ARABIC", "HEBREW"}

    def process(self):
        """
        Reads items, and replaces any accented characters with their unaccented version.
        """

        columns = self.parameters.get("columns")
        casefold = self.parameters.get("case-fold")
        mode = self.parameters.get("mode")

        folding_method = self.case_fold if mode == "fold" else unidecode

        with self.dataset.get_results_path().open("w", encoding="utf-8") as outfile:
            processed_items = 0
            writer = None

            for item in self.source_dataset.iterate_items(self):
                if not writer:
                    # initialise csv writer - we do this explicitly rather than
                    # using self.write_items_and_finish() because else we have
                    # to store a potentially very large amount of items in
                    # memory which is not a good idea
                    writer = csv.DictWriter(outfile, fieldnames=item.keys())
                    writer.writeheader()

                processed_items += 1
                if processed_items % 500 == 0:
                    self.dataset.update_status(
                        "Processed %i/%i items" % (processed_items, self.source_dataset.num_rows))
                    self.dataset.update_progress((processed_items / self.source_dataset.num_rows))

                for field in columns:
                    if field not in item:
                        continue
                    if type(item[field]) is not str:
                        continue

                    value = folding_method(item[field], errors="preserve")
                    item[field] = value

                if casefold:
                    for field, value in item.items():
                        if type(item[field]) is not str:
                            continue

                        item[field] = item[field].lower()

                writer.writerow(item)

        self.dataset.finish(processed_items)

    def after_process(self):
        super().after_process()

        # Request standalone
        self.create_standalone()

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

        options = {
            "mode": {
                "help": "What to replace?",
                "type": UserInput.OPTION_CHOICE,
                "options": {
                    "fold": "Remove accents from Latin, Greek, Arabic and Hebrew letters",
                    "transliterate": "Rewrite all text in Latin letters (ASCII)"
                },
                "default": "fold",
                "tooltip": "On social media, people often leave out accents. Removing them makes 'canción' and "
                           "'cancion' the same word. Text in other scripts, such as Korean, Chinese or Japanese, "
                           "does not change. Rewriting in Latin letters changes all text, e.g. '北亰' becomes "
                           "'Bei Jing' and '한국어' becomes 'hangugeo'. This loses information and is rarely useful "
                           "for analysis."
            },
            "case-fold": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Also convert all text to lowercase",
                "default": False
            },
            "columns": {
                "type": UserInput.OPTION_TEXT,
                "help": "Column(s) to apply folding on",
                "inline": True,
                "default": "body",
            }
        }

        if parent_dataset and parent_dataset.get_columns():
            columns = parent_dataset.get_columns()
            options["columns"]["type"] = UserInput.OPTION_MULTI
            options["columns"]["options"] = {v: v for v in columns}
            options["columns"]["default"] = columns

        return options

    @staticmethod
    def case_fold(text, errors=None):
        """
        Remove accents from Latin, Greek, Arabic and Hebrew letters

        Each character is split into its letter and its marks ('é' into 'e'
        and an accent). The marks on letters in these four scripts are left
        out, because people often leave them out when they write, e.g. on
        social media. Marks in other scripts are kept. There they are part of
        the letter, and leaving them out changes the word, e.g. Japanese 'が'
        becomes 'か' and Russian 'й' becomes 'и'.

        Thanks to https://stackoverflow.com/a/518232.

        :param text:  Text to fold
        :param errors:  Dummy parameter for compatibility with unidecode
        :return:  Folded text
        """
        kept = []
        base = None
        for c in unicodedata.normalize('NFD', text):
            if unicodedata.category(c) != 'Mn':
                base = c
            # only marks on letters, so that e.g. an emoji such as '🅿️' keeps
            # its variation selector, even though its name has 'LATIN' in it
            elif base and unicodedata.category(base).startswith("L") and \
                    AccentFoldingFilter.FOLDED_SCRIPTS & set(unicodedata.name(base, "").split()):
                continue

            kept.append(c)

        # put back together what was split but kept, e.g. Hangul syllables,
        # else the text looks the same but no longer matches searches or
        # word lists
        return unicodedata.normalize('NFC', ''.join(kept))
