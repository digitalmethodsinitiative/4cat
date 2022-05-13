"""
Fold accents, case, and diacritics.
"""
import unicodedata
import csv

from unidecode import unidecode
from backend.abstract.processor import BasicProcessor
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
    title = "Replace or transliterate accented and non-Latin characters"  # title displayed in UI
    description = "Replaces non-latin characters with the closest ASCII equivalent, convertng e.g. 'á' to 'a', 'ç' " \
                  "to 'c', et cetera. Creates a new dataset."
    extension = "csv"  # extension of result file, used internally and in UI

    options = {
        "mode": {
            "help": "What to replace?",
            "type": UserInput.OPTION_CHOICE,
            "options": {
                "fold": "Fold only accented latin characters",
                "transliterate": "Transliterate non-ASCII characters"
            },
            "default": "fold",
            "tooltip": "Transliteration will ensure that only pure ASCII characters are left, but makes larger changes"
                       " to the text (i.e. 北亰 is replaced with 'Bei Jing'). Folding will only replace accented "
                       "characters with their closest un-accented ASCII equivalent, e.g. á -> a."
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

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Allow processor on iterable files

        :param module: Dataset or processor to determine compatibility with
        """
        return module.is_top_dataset() and module.get_extension() in ["csv", 'ndjson']

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

                for field in columns:
                    value = folding_method(item[field], errors="preserve")
                    item[field] = value

                if casefold:
                    for field, value in item.items():
                        item[field] = item[field].lower()

                writer.writerow(item)

        self.dataset.finish(processed_items)

    def after_process(self):
        super().after_process()

        # Request standalone
        self.create_standalone()

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        Get processor options

        This method by default returns the class's "options" attribute, or an
        empty dictionary. It can be redefined by processors that need more
        fine-grained options, e.g. in cases where the availability of options
        is partially determined by the parent dataset's parameters.

        :param DataSet parent_dataset:  An object representing the dataset that
        the processor would be run on
        :param User user:  Flask user the options will be displayed for, in
        case they are requested for display in the 4CAT web interface. This can
        be used to show some options only to privileges users.
        """
        options = cls.options

        if parent_dataset and parent_dataset.get_columns():
            columns = parent_dataset.get_columns()
            options["columns"]["type"] = UserInput.OPTION_MULTI
            options["columns"]["options"] = {v: v for v in columns}
            options["columns"]["default"] = columns

        return options

    @staticmethod
    def case_fold(text, errors=None):
        """
        Case-folding function for processing text

        Thanks to https://stackoverflow.com/a/518232.

        :param text:  Text to case-fold
        :param errors:  Dummy parameter for compatibility with unidecode
        :return:  Case-folded text
        """
        return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')
