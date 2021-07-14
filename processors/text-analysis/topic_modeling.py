"""
Create topic clusters based on datasets
"""

from common.lib.helpers import UserInput
from backend.abstract.processor import BasicProcessor

import json

from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.decomposition import LatentDirichletAllocation

__author__ = ["Stijn Peeters"]
__credits__ = ["Stijn Peeters"]
__maintainer__ = ["Stijn Peeters"]
__email__ = "4cat@oilab.eu"


class TopicModeler(BasicProcessor):
    """
    Tokenize posts
    """
    type = "topic-modeler"  # job type ID
    category = "Text analysis"  # category
    title = "Topic modeling"  # title displayed in UI
    description = "Let's model some topics"  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    options = {
        "vectoriser": {
            "type": UserInput.OPTION_CHOICE,
            "options": {
                "count": "Frequency",
                "tf-idf": "Tf-idf"
            },
            "default": "count",
            "help": "Vectorisation method",
            "tooltip": "Tf-idf will reduce the influence of common words, for sparser but more specific topics"
        },
        "topics": {
            "type": UserInput.OPTION_TEXT,
            "min": 2,
            "max": 50,
            "default": 10,
            "help": "Number of topics",
            "tooltip": "Topics will be divided in this many clusters. Should be between 2 and 50."
        },
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
    def is_compatible_with(cls, dataset=None):
        """
        Allow processor on token sets

        :param DataSet dataset:  Dataset to determine compatibility with
        """
        return dataset.type == "tokenise-posts"

    def process(self):
        """
        Unzips token sets, vectorises them and zips them again.
        """

        # prepare staging area
        results = []

        self.dataset.update_status("Processing token sets")
        vectoriser_class = TfidfVectorizer if self.parameters.get("vectoriser") == "tf-idf" else CountVectorizer

        # go through all archived token sets and vectorise them
        index = 0
        for token_file in self.iterate_archive_contents(self.source_file):
            index += 1
            self.dataset.update_status("Processing token set %i (%s)" % (index, token_file.stem))

            # temporarily extract file (we cannot use ZipFile.open() as it doesn't support binary modes)
            with token_file.open("rb") as binary_tokens:
                tokens = json.load(binary_tokens)

            self.dataset.update_status("Vectorising token set '%s'" % token_file.stem)
            vectoriser = vectoriser_class(tokenizer=lambda token: token, lowercase=False)
            vectors = vectoriser.fit_transform(tokens)
            features = vectoriser.get_feature_names()

            self.dataset.update_status("Fitting token clusters for token set '%s'" % token_file.stem)
            model = LatentDirichletAllocation(n_components=self.parameters.get("topics"), random_state=0)
            model.fit(vectors)

            self.dataset.update_status("Storing topics for token set '%s'" % token_file.stem)

            for topic in model.components_:
                top_features = {features[i]: weight for i, weight in enumerate(topic)}
                top_features = {f: top_features[f] for f in sorted(top_features, key=lambda k: top_features[k], reverse=True)[:10]}
                result = {
                    "interval": token_file.stem
                }

                for index, word in enumerate(top_features):
                    index += 1
                    result["word_%i" % index] = word
                    result["weight_%i" % index] = top_features[word]

                results.append(result)

        self.write_csv_items_and_finish(results)

