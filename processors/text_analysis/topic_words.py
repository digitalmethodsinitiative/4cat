"""
Extracts topics per model and top associated words
"""

from common.lib.helpers import UserInput
from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException

import pickle

__author__ = ["Stijn Peeters"]
__credits__ = ["Stijn Peeters", "Sal Hagen"]
__maintainer__ = ["Stijn Peeters"]
__email__ = "4cat@oilab.eu"


class TopicModelWordExtractor(BasicProcessor):
    """
    Extracts topics per model and top associated words
    """
    type = "topic-model-words"  # job type ID
    category = "Text analysis"  # category
    title = "Top words per topic"  # title displayed in UI
    description = "Creates a CSV file with the top tokens (words) per topic in the generated topic model, and their associated weights."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    options = {
        "topic_size": {
            "type": UserInput.OPTION_TEXT,
            "min": 1,
            "max": 100,
            "default": 10,
            "help": "Tokens per topic",
            "tooltip": "This many of the most relevant tokens will be retained per topic"
        }
    }

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Allow processor on topic models

        :param module: Dataset or processor to determine compatibility with
        """
        return module.type == "topic-modeller"

    def process(self):
        """
        Extracts topics per model and top associated words
        """
        self.dataset.update_status("Unpacking topic models")
        staging_area = self.unpack_archive_contents(self.source_file)
        results = []

        for model_file in staging_area.glob("*.model"):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while extracting topic model tokens")

            self.dataset.update_status("Extracting topics from model '%s'" % model_file.stem)
            with model_file.open("rb") as infile:
                model = pickle.load(infile)

            with model_file.with_suffix(".features").open("rb") as infile:
                features = pickle.load(infile)

            topic_index = 0
            for topic in model.components_:
                topic_index += 1
                top_features = {features[i]: weight for i, weight in enumerate(topic)}
                top_features = {f: top_features[f] for f in
                                sorted(top_features, key=lambda k: top_features[k], reverse=True)[:self.parameters.get("topic_size")]}
                result = {
                    "date": model_file.stem,
                    "topic_number": topic_index
                }

                for index, word in enumerate(top_features):
                    index += 1
                    result["word_%i" % index] = word
                    result["weight_%i" % index] = top_features[word]

                results.append(result)

        self.write_csv_items_and_finish(results)
