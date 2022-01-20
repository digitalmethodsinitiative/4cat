"""
Extract nouns from SpaCy NLP docs.

"""

import csv
import pickle
import shutil
import spacy

from collections import Counter
from spacy.tokens import DocBin
from common.lib.helpers import UserInput
from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


class ExtractNouns(BasicProcessor):  # TEMPORARILY DISABLED
    """
    Rank vectors over time
    """
    type = "get-entities"  # job type ID
    category = "Text analysis"  # category
    title = "Extract named entities"  # title displayed in UI
    description = "Get the prediction of various named entities from a text, ranked on frequency. Be sure to have selected \"Named Entity Recognition\" in the previous module. Currently only available for datasets with less than 25.000 items."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    options = {
        "entities": {
            "type": UserInput.OPTION_MULTI,
            "default": [],
            "options": {
                "PERSON": "PERSON: People, including fictional.",
                "NORP": "NORP: Nationalities or religious or political groups.",
                "FAC": "FAC: Buildings, airports, highways, bridges, etc.",
                "ORG": "ORG: Companies, agencies, institutions, etc.",
                "GPE": "GPE: Countries, cities, states.",
                "LOC": "LOC: Non-GPE locations, mountain ranges, bodies of water.",
                "PRODUCT": "PRODUCT: Objects, vehicles, foods, etc. (Not services.)",
                "EVENT": "EVENT: Named hurricanes, battles, wars, sports events, etc.",
                "WORK_OF_ART": "WORK_OF_ART: Titles of books, songs, etc.",
                "LAW": "LAW: Named documents made into laws.",
                "LANGUAGE": "LANGUAGE: Any named language.",
                "DATE": "DATE: Absolute or relative dates or periods.",
                "TIME": "TIME: Times smaller than a day.",
                "PERCENT": "PERCENT: Percentage, including ”%“.",
                "MONEY": "MONEY: Monetary values, including unit.",
                "QUANTITY": "QUANTITY: Measurements, as of weight or distance.",
                "ORDINAL": "ORDINAL: “first”, “second”, etc.",
                "CARDINAL": "CARDINAL: Numerals that do not fall under another type."
            },
            "help": "What types of entities to extract (select at least one)",
            "tooltip": "The above list is derived from the SpaCy documentation (see references)."
        }
    }

    references = [
        "[SpaCy named entities list](https://spacy.io/api/annotation#named-entities)"
    ]

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Allow processor on linguistic feature data

        :param module: Dataset or processor to determine compatibility with
        """

        return module.type == "linguistic-features"

    def process(self):
        """
        Opens the SpaCy output and gets ze entities.

        """

        # Validate whether the user enabled the right parameters.
        if "ner" not in self.source_dataset.parameters["enable"]:
            self.dataset.update_status("Enable \"Named entity recognition\" in previous module")
            self.dataset.finish(0)
            return

        if self.source_dataset.num_rows > 25000:
            self.dataset.update_status(
                "Named entity recognition is only available for datasets smaller than 25.000 items.")
            self.dataset.finish(0)
            return

        else:
            # Extract the SpaCy docs first
            self.dataset.update_status("Unzipping SpaCy docs")

            # Store all the entities in this list
            li_entities = []
            nlp = spacy.load("en_core_web_sm")  # Load model

            for doc_file in self.iterate_archive_contents(self.source_file):
                with doc_file.open("rb") as pickle_file:
                    # Load DocBin
                    file = pickle.load(pickle_file)
                    doc_bin = DocBin().from_bytes(file)
                    docs = list(doc_bin.get_docs(nlp.vocab))

                for doc in docs:
                    post_entities = []

                    # stop processing if worker has been asked to stop
                    if self.interrupted:
                        raise ProcessorInterruptedException("Interrupted while processing documents")

                    for ent in doc.ents:
                        if ent.label_ in self.parameters["entities"]:
                            post_entities.append((ent.text, ent.label_))  # Add a tuple

                    li_entities.append(post_entities)

            results = []

            if li_entities:

                # Also add the data to the original file, if indicated.
                if self.parameters.get("overwrite"):
                    self.add_field_to_parent(field_name='named_entities',
                                             # Format like "Apple:ORG, Gates:PERSON, ..." and add to the row
                                             new_data=[", ".join([":".join(post_entities) for post_entities in entity]) for entity in li_entities],
                                             which_parent=self.dataset.top_parent())

                all_entities = []
                # Convert to lower and filter out one-letter words. Join the words with the entities so we can group easily.
                for post_ents in li_entities:
                    for pair in post_ents:
                        if pair and len(pair[0]) > 1:
                            pair = pair[0].lower() + " |#| " + pair[1]
                            all_entities.append(pair)

                # Group and rank
                count_nouns = Counter(all_entities).most_common()
                # Unsplit and list the count.
                results = [{"word": tpl[0].split(" |#| ")[0], "entity": tpl[0].split(" |#| ")[1], "count": tpl[1]} for
                           tpl in count_nouns]

            # done!
            if results:
                self.dataset.update_status("Finished")
                self.write_csv_items_and_finish(results)
            else:
                self.dataset.update_status("Finished, but no entities were extracted.")
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
                "tooltip": "Will add a column (\"nouns\", \"nouns_and_compounds\", or \"noun_chunks\"), and the found nouns in the post row."
            }

        return options
