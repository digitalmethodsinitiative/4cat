"""
Project word embedding vectors for to a 2D space and highlight given words
"""
import shutil
import numpy
import csv
import sys

from sklearn.manifold import TSNE
from sklearn.decomposition import PCA, TruncatedSVD

from gensim.models import KeyedVectors

from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput, convert_to_int, get_4cat_canvas
from common.lib.exceptions import ProcessorInterruptedException

from svgwrite.container import SVG
from svgwrite.shapes import Line
from svgwrite.text import Text
from svgwrite.filters import Filter

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)


class HistWordsVectorSpaceVisualiser(BasicProcessor):
    """
    Project word embedding vectors for to a 2D space and highlight given words

    Based on Hamilton et al.'s 'HistWords' algorithm. Reduces vectors to two
    dimensions, plots them, and highlights given words and their neighbours.
    """
    type = "histwords-vectspace"  # job type ID
    category = "Visual"  # category
    title = "Chart diachronic nearest neighbours"  # title displayed in UI
    description = "Visualise nearest neighbours of a given query across all models and show the closest neighbours per model in one combined graph. Based on the 'HistWords' algorithm by Hamilton et al."  # description displayed in UI
    extension = "svg"  # extension of result file, used internally and in UI

    references = [
        "HistWords: [Hamilton, W. L., Leskovec, J., & Jurafsky, D. (2016). Diachronic word embeddings reveal statistical laws of semantic change. *arXiv preprint** arXiv:1605.09096.](https://arxiv.org/pdf/1605.09096.pdf)",
        "HistWords: [William L. Hamilton, Jure Leskovec, and Dan Jurafsky. HistWords: Word Embeddings for Historical Text](https://nlp.stanford.edu/projects/histwords/)",
        "t-SNE: [Maaten, L. V. D., & Hinton, G. (2008). Visualizing data using t-SNE. *Journal of machine learning research*, 9(Nov), 2579-2605.](https://www.jmlr.org/papers/v9/vandermaaten08a.html)",
        "PCA: [Joliffe, I. T., & Morgan, B. J. T. (1992). Principal component analysis and exploratory factor analysis. *Statistical methods in medical research*, 1(1), 69-95.](https://journals.sagepub.com/doi/abs/10.1177/096228029200100105)",
        "Truncated SVD: [Manning, C. D., Raghavan, P., & Schütze, H. (2008). Matrix decompositions and latent semantic indexing. *Introduction to information retrieval*, 403-417.](http://nlp.stanford.edu/IR-book/pdf/18lsi.pdf)"
    ]

    options = {
        "words": {
            "type": UserInput.OPTION_TEXT,
            "help": "Word(s)",
            "tooltip": "Nearest neighbours for these words will be charted, and the position of the words will be highlighted"
        },
        "method": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Vector dimensionality reduction technique",
            "options": {
                "t-SNE": "t-SNE (learning rate: 150)",
                "PCA": "PCA",
                "TruncatedSVD": "Truncated SVD (randomised, 5 iterations)"
            },
            "default": "tsne"
        },
        "num-words": {
            "type": UserInput.OPTION_TEXT,
            "help": "Amount of nearest neighbours",
            "min": 1,
            "default": 15,
            "max": 100,
            "tooltip": "Amount of neighbours to chart per model, per queried word"
        },
        "threshold": {
            "type": UserInput.OPTION_TEXT,
            "help": "Similarity threshold",
            "tooltip": "Decimal value between 0 and 1; only neighbours with a higher similarity score than this will be included",
            "default": "0.3"
        },
        "overlay": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Plot all models",
            "default": True,
            "tooltip": "Plot similar words for all models. If unchecked, only similar words for the most recent model will be plotted."
        },
        "all-words": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Always include all words",
            "default": False,
            "tooltip": "If checked, plot the union of all nearest neighbours for all models, even if a word is not a nearest neighbour for that particular model."
        }
    }

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Allow processor on token sets

        :param module: Dataset or processor to determine compatibility with
        """
        return module.type == "generate-embeddings"

    def process(self):
        # parse parameters
        input_words = self.parameters.get("words", "")
        if not input_words or not input_words.split(","):
            self.dataset.update_status("No input words provided, cannot look for similar words.", is_final=True)
            self.dataset.finish(0)
            return

        input_words = input_words.split(",")

        try:
            threshold = float(self.parameters.get("threshold"))
        except ValueError:
            threshold = float(self.get_options()["threshold"]["default"])

        threshold = max(-1.0, min(1.0, threshold))
        num_words = convert_to_int(self.parameters.get("num-words"))
        overlay = self.parameters.get("overlay")
        reduction_method = self.parameters.get("method")
        all_words = self.parameters.get("all-words")

        # load model files and initialise
        self.dataset.update_status("Unpacking word embedding models")
        staging_area = self.unpack_archive_contents(self.source_file)
        common_vocab = None
        vector_size = None
        models = {}

        # find words that are common to all models
        self.dataset.update_status("Determining cross-model common vocabulary")
        for model_file in staging_area.glob("*.model"):
            if self.interrupted:
                shutil.rmtree(staging_area)
                raise ProcessorInterruptedException("Interrupted while processing word embedding models")

            model = KeyedVectors.load(str(model_file)).wv
            models[model_file.stem] = model
            if vector_size is None:
                vector_size = model.vector_size  # needed later for dimensionality reduction

            if common_vocab is None:
                common_vocab = set(model.vocab.keys())
            else:
                common_vocab &= set(model.vocab.keys())  # intersect

        if not common_vocab:
            self.dataset.update_status("No vocabulary common across all models, cannot diachronically chart words", is_final=True)
            return

        # sort common vocabulary by combined frequency across all models
        # this should make filtering for common words a bit faster further down
        self.dataset.update_status("Sorting vocabulary")
        common_vocab = list(common_vocab)
        common_vocab.sort(key=lambda w: sum([model.vocab[w].count for model in models.values()]), reverse=True)

        # initial boundaries of 2D space (to be adjusted later based on t-sne
        # outcome)
        max_x = 0.0 - sys.float_info.max
        max_y = 0.0 - sys.float_info.max
        min_x = sys.float_info.max
        min_y = sys.float_info.max

        # for each model, find the words that we may want to plot - these are
        # the nearest neighbours for the given query words
        relevant_words = {}

        # the vectors need to be reduced all at once - but the vectors are
        # grouped by model. To solve this, keep one numpy array of vectors,
        # but also keep track of which indexes of this array belong to which
        # model, by storing the index of the first vector for a model
        vectors = numpy.empty((0, vector_size))
        vector_offsets = {}

        # now process each model
        for model_name, model in models.items():
            relevant_words[model_name] = set()  # not a set, since order needs to be preserved
            self.dataset.update_status("Finding similar words in model '%s'" % model_name)

            for query in input_words:
                if query not in model.vocab:
                    self.dataset.update_status("Query '%s' was not found in model %s; cannot find nearest neighbours." % (query, model_name), is_final=True)
                    self.dataset.finish(0)
                    return

                if self.interrupted:
                    shutil.rmtree(staging_area)
                    raise ProcessorInterruptedException("Interrupted while finding similar words")

                # use a larger sample (topn) than required since some of the
                # nearest neighbours may not be in the common vocabulary and
                # will therefore need to be ignored
                context = set([word[0] for word in model.most_similar(query, topn=1000) if
                                word[0] in common_vocab and word[1] >= threshold][:num_words])

                relevant_words[model_name] |= {query} | context  # always include query word

        # now do another loop to determine which words to plot for each model
        # this is either the same as relevant_words, or a superset which
        # combines all relevant words for all models
        plottable_words = {}
        last_model = max(relevant_words.keys())
        all_relevant_words = set().union(*relevant_words.values())

        for model_name, words in relevant_words.items():
            plottable_words[model_name] = []
            vector_offsets[model_name] = len(vectors)

            # determine which words to plot for this model. either the nearest
            # neighbours for this model, or all nearest neighbours found across
            # all models
            words_to_include = all_relevant_words if all_words else relevant_words[model_name]

            for word in words_to_include:
                if word in plottable_words[model_name] or (not overlay and model_name != last_model and word not in input_words):
                    # only plot each word once per model, or if 'overlay'
                    # is not set, only once overall (for the most recent
                    # model)
                    continue

                vector = models[model_name][word]
                plottable_words[model_name].append(word)
                vectors = numpy.append(vectors, [vector], axis=0)

        del models  # no longer needed

        # reduce the vectors of all words to be plotted for this model to
        # a two-dimensional coordinate with the previously initialised tsne
        # transformer. here the two-dimensional vectors are interpreted as
        # cartesian coordinates
        if reduction_method == "PCA":
            pca = PCA(n_components=2, random_state=0)
            vectors = pca.fit_transform(vectors)
        elif reduction_method == "t-SNE":
            # initialise t-sne transformer
            # parameters taken from Hamilton et al.
            # https://github.com/williamleif/histwords/blob/master/viz/common.py
            tsne = TSNE(n_components=2, random_state=0, learning_rate=150, init="pca")
            vectors = tsne.fit_transform(vectors)
        elif reduction_method == "TruncatedSVD":
            # standard sklearn parameters made explicit
            svd = TruncatedSVD(n_components=2, algorithm="randomized", n_iter=5, random_state=0)
            vectors = svd.fit_transform(vectors)
        else:
            shutil.rmtree(staging_area)
            self.dataset.update_status("Invalid dimensionality reduction technique selected", is_final=True)
            self.dataset.finish(0)
            return

        # also keep track of the boundaries of our 2D space, so we can plot
        # them properly later
        for position in vectors:
            max_x = max(max_x, position[0])
            max_y = max(max_y, position[1])
            min_x = min(min_x, position[0])
            min_y = min(min_y, position[1])

        # now we know for each model which words should be plotted and at what
        # position
        # with this knowledge, we can normalize the positions, and start
        # plotting them in a graph

        # a palette generated with https://medialab.github.io/iwanthue/
        colours = ["#d58eff", "#cf9000", "#3391ff", "#a15700", "#911ca7", "#00ddcb", "#cc25a9", "#d5c776", "#6738a8",
                   "#ff9470", "#47c2ff", "#a4122c", "#00b0ca", "#9a0f76", "#ff70c8", "#713c88"]
        colour_index = 0

        # make sure all coordinates are positive
        max_x -= min_x
        max_y -= min_y

        # determine graph dimensions and proportions
        width = 1000  # arbitrary
        height = width * (max_y / max_x)  # retain proportions
        scale = width / max_x

        # margin around the plot to give room for labels and to look better
        margin = width * 0.1
        width += 2 * margin
        height += 2 * margin

        # normalize all known positions to fit within the graph
        vectors = [(margin + ((position[0] - min_x) * scale), margin + ((position[1] - min_y) * scale)) for position in
                   vectors]

        # now all positions are finalised, we can determine the "journey" of
        # each query - the sequence of positions in the graph it takes, so we
        # can draw lines from position to position later
        journeys = {}
        for query in input_words:
            journeys[query] = []
            for model_name, words in plottable_words.items():
                index = words.index(query)
                journeys[query].append(vectors[vector_offsets[model_name] + index])

        # font sizes proportional to width (which is static and thus predictable)
        fontsize_large = width / 50
        fontsize_normal = width / 75
        fontsize_small = width / 100

        # now we have the dimensions, the canvas can be instantiated
        model_type = self.source_dataset.parameters.get("model-type", "word2vec")
        canvas = get_4cat_canvas(self.dataset.get_results_path(), width, height,
                                 header="%s nearest neighbours (fitting: %s) - '%s'" % (model_type, reduction_method, ",".join(input_words)),
                                 fontsize_normal=fontsize_normal,
                                 fontsize_large=fontsize_large,
                                 fontsize_small=fontsize_small)

        # use colour-coded backgrounds to distinguish the query words in the
        # graph, each model (= interval) with a separate colour
        for model_name in plottable_words:
            solid = Filter(id="solid-%s" % model_name)
            solid.feFlood(flood_color=colours[colour_index])
            solid.feComposite(in_="SourceGraphic")
            canvas.defs.add(solid)

            # this can get kind of confusing, but you shouldn't be using this
            # with more than 16 models anyway
            colour_index = 0 if colour_index >= len(colours) - 1 else colour_index + 1

        # now plot each word for each model
        self.dataset.update_status("Plotting graph")
        words = SVG(insert=(0, 0), size=(width, height))
        queries = SVG(insert=(0, 0), size=(width, height))
        colour_index = 0

        for model_name, labels in plottable_words.items():
            positions = vectors[vector_offsets[model_name]:vector_offsets[model_name] + len(labels)]

            label_index = 0
            for position in positions:
                word = labels[label_index]
                is_query = word in input_words
                label_index += 1

                filter = ("url(#solid-%s)" % model_name) if is_query else "none"
                colour = "#FFF" if is_query else colours[colour_index]
                fontsize = fontsize_normal if is_query else fontsize_small

                if word in input_words:
                    word += " (" + model_name + ")"

                label_container = SVG(insert=position, size=(1, 1), overflow="visible")
                label_container.add(Text(
                    insert=("50%", "50%"),
                    text=word,
                    dominant_baseline="middle",
                    text_anchor="middle",
                    style="fill:%s;font-size:%ipx" % (colour, fontsize),
                    filter=filter
                ))

                # we make sure the queries are always rendered on top by
                # putting them in a separate SVG container
                if is_query:
                    queries.add(label_container)
                else:
                    words.add(label_container)

            colour_index = 0 if colour_index >= len(colours) - 1 else colour_index + 1

        # plot a line between positions for query words
        lines = SVG(insert=(0, 0), size=(width, height))
        for query, journey in journeys.items():
            previous_position = None
            for position in journey:
                if previous_position is None:
                    previous_position = position
                    continue

                lines.add(Line(start=previous_position, end=position,
                               stroke="#CE1B28", stroke_width=2))
                previous_position = position

        canvas.add(lines)
        canvas.add(words)
        canvas.add(queries)

        canvas.save(pretty=True)
        shutil.rmtree(staging_area)
        self.dataset.finish(len(journeys))
