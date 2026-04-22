"""
Create topic clusters based on datasets
"""

from common.lib.helpers import UserInput
from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException

import json
import pickle
import shutil

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
    description = "Creates topic models per token set using Latent Dirichlet Allocation (LDA). " \
                  "For a given number of topics, tokens are assigned a relevance weight per topic, " \
                  "which can be used to find clusters of related words."  # description displayed in UI
    extension = "zip"  # extension of result file, used internally and in UI

    followups = ["document_count", "document_topic_matrix", "topic-model-words"]
    references = [
        'Blei, David M., Andrew Y. Ng, and Michael I. Jordan (2003). "Latent dirichlet allocation." the *Journal of machine Learning research* 3: 993-1022.',
        'Blei, David M. (2003). "Topic Modeling and Digital Humanities." *Journal of Digital Humanities* 2(1).'
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

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Allow processor on token sets

        :param module: Module to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
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

        model_metadata = {'parameters': self.parameters}
        # go through all archived token sets and vectorise them
        index = 0
        for token in self.source_dataset.iterate_items():
            # Check for and open token metadata file
            if token.file.name == '.token_metadata.json':
                # Copy the token metadata into our staging area
                shutil.copyfile(token.file, staging_area.joinpath(".token_metadata.json"))
                continue

            index += 1
            self.dataset.update_status("Processing token set %i (%s)" % (index, token.file.stem))
            self.dataset.update_progress(index / self.source_dataset.num_rows)

            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while topic modeling")

            # temporarily extract file (we cannot use ZipFile.open() as it doesn't support binary modes)
            with token.file.open("rb") as binary_tokens:
                tokens = json.load(binary_tokens)

            self.dataset.update_status("Vectorising token set '%s'" % token.file.stem)
            vectoriser = vectoriser_class(tokenizer=token_helper, lowercase=False, min_df=min_df, max_df=max_df)

            try:
                vectors = vectoriser.fit_transform(tokens)
            except ValueError as e:
                # 'no words left' after pruning, so nothing to model with
                self.dataset.finish_with_error(str(e))
                return

            features = vectoriser.get_feature_names_out()

            self.dataset.update_status("Fitting token clusters for token set '%s'" % token.file.stem)
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while fitting LDA model")

            model = LatentDirichletAllocation(n_components=self.parameters.get("topics"), random_state=0)
            model.fit(vectors)

            # store features too, because we need those to later know what
            # tokens the modeled weights correspond to
            self.dataset.update_status("Storing model for token set '%s'" % token.file.stem)
            with staging_area.joinpath("%s.features" % token.file.stem).open("wb") as outfile:
                pickle.dump(features, outfile)

            with staging_area.joinpath("%s.model" % token.file.stem).open("wb") as outfile:
                pickle.dump(model, outfile)

            # Storing vectors and vectoriser for LDA visualisation
            self.dataset.update_status("Storing vectors and vectoriser for token set '%s'" % token.file.stem)
            with staging_area.joinpath("%s.vectors" % token.file.stem).open("wb") as outfile:
                pickle.dump(vectors, outfile)

            with staging_area.joinpath("%s.vectoriser" % token.file.stem).open("wb") as outfile:
                pickle.dump(vectoriser, outfile)

            # Collect Metadata
            model_topics = {}
            for topic_index, topic in enumerate(model.components_):
                model_features = {features[i]: weight for i, weight in enumerate(topic)}
                top_five_features = {f: model_features[f] for f in
                                sorted(model_features, key=lambda k: model_features[k], reverse=True)[:5]}
                model_topics[topic_index] = {
                                            'topic_index': topic_index,
                                            'top_five_features': top_five_features,
                                            }
            model_metadata[token.file.name] = {
                                          'model_file': "%s.model" % token.file.stem,
                                          'feature_file': "%s.features" % token.file.stem,
                                          'source_token_file': token.file.name,
                                          'model_topics': model_topics,
                                          }

            # Make predictions
            # This could be done in another processor, but we have the model right here
            predicted_topics = model.transform(vectors)
            model_metadata[token.file.name]['predictions'] = {i:{topic:unnormalized_distribution for topic, unnormalized_distribution in enumerate(doc_predictions)} for i, doc_predictions in enumerate(predicted_topics)}

        # Save the model metadata in our staging area
        with staging_area.joinpath(".model_metadata.json").open("w", encoding="utf-8") as outfile:
            json.dump(model_metadata, outfile)

        self.dataset.update_status("Compressing generated model files")
        self.write_archive_and_finish(staging_area)

def token_helper(token):
    """
    pickle requires named functions
    """
    return token
