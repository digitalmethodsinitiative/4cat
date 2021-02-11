"""
Align word2vec models
"""
import numpy

from gensim.models import word2vec, KeyedVectors

from backend.abstract.processor import BasicProcessor
from backend.lib.exceptions import ProcessorInterruptedException

import shutil

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen", "Stijn Peeters"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


class AlignWord2VecModels(BasicProcessor):
    """
    Align word2vec models
    """
    type = "align-word2vec"  # job type ID
    category = "Text analysis"  # category
    title = "Align Word2vec models"  # title displayed in UI
    description = "Processes a number of word2vec models to only retain vocabulary that exists in all models"  # description displayed in UI
    extension = "zip"  # extension of result file, used internally and in UI

    accepts = ["generate-word2vec"]

    input = "zip"
    output = "zip"

    def process(self):
        """
        This takes previously generated Word2Vec models and uses them to find
        similar words based on a list of words
        """
        self.dataset.update_status("Processing sentences")

        # retain words that are common to all models
        staging_area = self.unpack_archive_contents(self.source_file)
        common_vocab = None
        models = {}
        for model_file in staging_area.glob("*.model"):
            if self.interrupted:
                shutil.rmtree(staging_area)
                raise ProcessorInterruptedException("Interrupted while processing word2vec models")

            model = KeyedVectors.load(str(model_file))
            models[str(model_file)] = model

            if common_vocab is None:
                common_vocab = set(model.vocab.keys())
            else:
                common_vocab = common_vocab.intersection(set(model.vocab.keys()))

            # prime model for further editing
            # if we don't do this "vectors_norm" will not be available later
            try:
                model.most_similar("4cat")
            except KeyError:
                pass

        # sort common vocabulary by combined frequency across all models
        common_vocab = list(common_vocab)
        common_vocab.sort(key=lambda w: sum([model.vocab[w].count for model in models.values()]), reverse=True)

        # remove model data for words not in common vocabulary
        for model_file, model in models.items():
            if self.interrupted:
                shutil.rmtree(staging_area)
                raise ProcessorInterruptedException("Interrupted while reducing word2vec models")

            indices = [model.vocab[word].index for word in common_vocab]

            new_vectors = numpy.array([model.vectors_norm[index] for index in indices])
            model.vectors_norm = model.syn0 = new_vectors

            model.index2word = common_vocab
            old_vocab = model.vocab
            new_vocab = {}
            for new_index, word in enumerate(common_vocab):
                word_data = old_vocab[word]
                new_vocab[word] = word2vec.Vocab(index=new_index, count=word_data.count)

            model.vocab = new_vocab
            model.save(model_file)

        self.write_archive_and_finish(staging_area)