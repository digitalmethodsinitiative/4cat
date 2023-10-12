"""
Extract nouns from SpaCy NLP docs.

"""
import pickle
import spacy

from collections import Counter
from spacy.tokens import DocBin
from common.lib.helpers import UserInput
from backend.lib.processor import BasicProcessor

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


class ExtractNouns(BasicProcessor):
    """
    Rank vectors over time
    """
    type = "extract-nouns"  # job type ID
    category = "Text analysis"  # category
    title = "Extract nouns"  # title displayed in UI
    description = "Retrieve nouns detected by SpaCy's part-of-speech tagging, and rank by frequency. " \
                  "Make sure to have selected \"Part of Speech\" in the previous " \
                  "module, as well as \"Dependency parsing\" if you want to extract compound nouns or noun chunks." # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    references = ["[Information on noun chunks](https://spacy.io/usage/linguistic-features#noun-chunks)"]

    options = {
        "type": {
            "type": UserInput.OPTION_CHOICE,
            "default": ["nouns"],
            "options": {
                "nouns": "Single-word nouns",
                "nouns_and_compounds": "Nouns and compound nouns",
                "noun_chunks": "Noun chunks"
            },
            "help": "Whether to only get 1) separate words indicated as nouns, 2) nouns and compound nouns " \
                    "(nouns with multiple words, e.g.\"United States\") using a custom parser, or 3) noun chunks: " \
                    "nouns plus the words describing them, e.g. \"the old grandpa\". See the references for more info."
        }
    }

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow processor on linguistic feature data

        :param module: Module to determine compatibility with
        """
        return module.type == "linguistic-features"

    def process(self):
        """
        Opens the SpaCy output and gets ze nouns.

        """
        noun_type = self.parameters["type"]

        # Validate whether the user enabled the right parameters.
        # Check part of speech tagging
        if "tagger" not in self.source_dataset.parameters["enable"]:
            self.dataset.update_status("Enable \"Part-of-speech tagging\" in previous module")
            self.dataset.finish(0)

        # Check dependency parsing if nouns and compouns nouns is selected
        elif (noun_type == "nouns_and_compounds" or noun_type == "noun_chunks") and "parser" not in \
                self.source_dataset.parameters["enable"]:
            self.dataset.update_status(
                "Enable \"Part-of-speech tagging\" and \"Dependency parsing\" for compound nouns/noun chunks in previous module")
            self.dataset.finish(0)

        # Valid parameters
        else:

            # Extract the SpaCy docs first
            self.dataset.update_status("Unzipping SpaCy docs")
            self.dataset.update_status("Extracting nouns")

            # Store all the nouns in this list
            li_nouns = []
            nlp = spacy.load("en_core_web_sm")  # Load model
            spacy.load("en_core_web_sm")

            for doc_file in self.iterate_archive_contents(self.source_file):
                with doc_file.open("rb") as pickle_file:
                    # Load DocBin
                    file = pickle.load(pickle_file)
                    doc_bin = DocBin().from_bytes(file)
                    docs = list(doc_bin.get_docs(nlp.vocab))

            # Simply add each word if its POS is "NOUN"
            if noun_type == "nouns":
                for doc in docs:
                    post_nouns = []
                    post_nouns += [token.text for token in doc if token.pos_ == "NOUN"]
                    li_nouns.append(post_nouns)

            # Use SpaCy's noun chunk detection
            elif noun_type == "noun_chunks":

                for doc in docs:

                    # Note: this is a workaround for now.
                    # Serialization of the SpaCy docs does not
                    # work well with dependency parsing after
                    # loading. Quick fix: parse again.

                    new_doc = nlp(doc.text)
                    post_nouns = []
                    for chunk in new_doc.noun_chunks:
                        post_nouns.append(chunk.text)

                    li_nouns.append(post_nouns)

            # Use a custom script to get single nouns and compound nouns
            elif noun_type == "nouns_and_compounds":
                for doc in docs:
                    post_nouns = []
                    noun = ""

                    for i, token in enumerate(doc):

                        # Check for common nouns (general, e.g. "people")
                        # and proper nouns (specific, e.g. "London")
                        if token.pos_ == "NOUN" or token.pos_ == "PROPN":
                            # Check if the token is part of a noun chunk
                            if token.dep_ == "compound":  # Check for a compound relation
                                noun = token.text
                            else:
                                if noun:
                                    noun += " " + token.text
                                    post_nouns.append(noun)
                                    noun = ""
                                else:
                                    post_nouns.append(token.text)
                    li_nouns.append(post_nouns)

            results = []

            if li_nouns:

                # Also add the data to the original file, if indicated.
                if self.parameters.get("overwrite"):
                    self.add_field_to_parent(field_name=noun_type,
                                             # Format like "apple, gates, ..." and add to the row
                                             new_data=[", ".join([post_noun.lower() for post_noun in li_noun if len(post_noun) > 1]) for li_noun in li_nouns],
                                             which_parent=self.dataset.top_parent())

                # convert to lower and filter out one-letter words
                all_nouns = []
                for post_n in li_nouns:
                    all_nouns += [str(cap_noun).lower() for cap_noun in post_n if len(cap_noun) > 1]

                # Group and rank
                count_nouns = Counter(all_nouns).most_common()
                results = [{"word": tpl[0], "count": tpl[1]} for tpl in count_nouns]

            # done!
            if results:
                self.dataset.update_status("Finished")
                self.write_csv_items_and_finish(results)
            else:
                self.dataset.update_status("Finished, but no nouns were extracted.")
                self.dataset.finish(0)

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        Get processor options

        The feature of this processor that overwrites the parent dataset can
        only work properly on csv datasets so check the extension before
        showing it.

        :param user:
        :param parent_dataset:  Dataset to get options for
        :return dict:
        """
        options = cls.options
        if parent_dataset and parent_dataset.top_parent().get_results_path().suffix in [".csv", ".ndjson"]:
            options["overwrite"] = {
                "type": UserInput.OPTION_TOGGLE,
                "default": False,
                "help": "Add extracted nouns to source csv",
                "tooltip": "Will add a column (\"nouns\", \"nouns_and_compounds\", or \"noun_chunks\"), and the found "
                           "nouns in the post row."
            }

        return options
