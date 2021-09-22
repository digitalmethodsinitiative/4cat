"""
Create topic clusters based on datasets
"""

from common.lib.helpers import UserInput
from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException

import json, pickle

from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.decomposition import LatentDirichletAllocation

__author__ = ["Stijn Peeters"]
__credits__ = ["Stijn Peeters", "Sal Hagen"]
__maintainer__ = ["Stijn Peeters"]
__email__ = "4cat@oilab.eu"


class TopicModeler(BasicProcessor):
    """
    Generate topic models
    """
    type = "topic-modeller"  # job type ID
    category = "Text analysis"  # category
    title = "Generate topic models"  # title displayed in UI
    description = "Creates topic models per token set using Latent Dirichlet Allocation (LDA). For a given number of topics, tokens are assigned a relevance weight per topic, which can be used to find clusters of related words."  # description displayed in UI
    extension = "zip"  # extension of result file, used internally and in UI

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
        "min_df": {
            "type": UserInput.OPTION_TEXT,
            "min": 0.0,
            "max": 1.0,
            "default": 0.01,
            "help": "Minimum document frequency",
            "tooltip": "Tokens are ignored if they do not occur in at least this fraction (between 0 and 1) of all tokenised items."
        },
        "max_df": {
            "type": UserInput.OPTION_TEXT,
            "min": 0.0,
            "max": 1.0,
            "default": 0.8,
            "help": "Maximum document frequency",
            "tooltip": "Tokens are ignored if they  occur in more than this fraction (between 0 and 1) of all tokenised items."
        }
    }

    references = [
        'Blei, David M., Andrew Y. Ng, and Michael I. Jordan (2003). "Latent dirichlet allocation." the *Journal of machine Learning research* 3: 993-1022.',
        'Blei, David M. (2003). "Topic Modeling and Digital Humanities." *Journal of Digital Humanities* 2(1).'
    ]

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Allow processor on token sets

        :param module: Dataset or processor to determine compatibility with
        """
        return module.type == "tokenise-posts"

    def process(self):
        """
        Unzips token sets and builds topic models for each one. Model data is
        pickle-dumped for later processing (e.g. visualisation).
        """

        self.dataset.update_status("Processing token sets")
        vectoriser_class = TfidfVectorizer if self.parameters.get("vectoriser") == "tf-idf" else CountVectorizer
        min_df = self.parameters.get("min_df")
        max_df = self.parameters.get("max_df")

        # prepare temporary location for model files
        staging_area = self.dataset.get_staging_area()

        # go through all archived token sets and vectorise them
        index = 0
        for token_file in self.iterate_archive_contents(self.source_file):
            index += 1
            self.dataset.update_status("Processing token set %i (%s)" % (index, token_file.stem))
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while topic modeling")

            # temporarily extract file (we cannot use ZipFile.open() as it doesn't support binary modes)
            with token_file.open("rb") as binary_tokens:
                tokens = json.load(binary_tokens)

            self.dataset.update_status("Vectorising token set '%s'" % token_file.stem)
            vectoriser = vectoriser_class(tokenizer=lambda token: token, lowercase=False, min_df=min_df, max_df=max_df)
            vectors = vectoriser.fit_transform(tokens)
            features = vectoriser.get_feature_names()

            self.dataset.update_status("Fitting token clusters for token set '%s'" % token_file.stem)
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while fitting LDA model")

            model = LatentDirichletAllocation(n_components=self.parameters.get("topics"), random_state=0)
            model.fit(vectors)

            # store features too, because we need those to later know what
            # tokens the modeled weights correspond to
            self.dataset.update_status("Storing model for token set '%s'" % token_file.stem)
            with staging_area.joinpath("%s.features" % token_file.stem).open("wb") as outfile:
                pickle.dump(features, outfile)

            with staging_area.joinpath("%s.model" % token_file.stem).open("wb") as outfile:
                pickle.dump(model, outfile)

        self.dataset.update_status("Compressing generated model files")
        self.write_archive_and_finish(staging_area)
