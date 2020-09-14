"""
Generate multiple area graphs and project them isometrically
"""
import shutil
import numpy
import csv
import sys

from sklearn.manifold import TSNE

from gensim.models import KeyedVectors

from backend.abstract.processor import BasicProcessor
from backend.lib.helpers import UserInput, convert_to_int
from backend.lib.exceptions import ProcessorInterruptedException

from svgwrite import Drawing
from svgwrite.container import SVG
from svgwrite.shapes import Line, Rect
from svgwrite.text import Text
from svgwrite.filters import Filter

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)


class HistWordsVectorSpaceVisualiser(BasicProcessor):
    """
    Generate multiple area graphs, and project them on an isometric plane

    Allows for easy side-by-side comparison of prevalence of multiple
    attributes in a data set over time.
    """
    type = "histwords-vectspace"  # job type ID
    category = "Visual"  # category
    title = "Chart diachronic nearest neighbours"  # title displayed in UI
    description = "Visualise nearest neighbours of a given query across all models and show the closest neighbours per model in one combined graph. Based on the 'HistWords' algorithm by Hamilton et al."  # description displayed in UI
    extension = "svg"  # extension of result file, used internally and in UI

    input = "zip"
    output = "svg"

    accepts = ["align-word2vec", "generate-word2vec"]
    references = [
        "[William L. Hamilton, Jure Leskovec, and Dan Jurafsky. ACL 2016. Diachronic Word Embeddings Reveal Statistical Laws of Semantic Change. ](https://arxiv.org/pdf/1605.09096.pdf)",
        "[William L. Hamilton, Jure Leskovec, and Dan Jurafsky. HistWords: Word Embeddings for Historical Text](https://nlp.stanford.edu/projects/histwords/)"
    ]

    options = {
        "words": {
            "type": UserInput.OPTION_TEXT,
            "help": "Query",
            "tooltip": "The position of this word will be highlighted in the graph"
        },
        "num-words": {
            "type": UserInput.OPTION_TEXT,
            "help": "Amount of similar words",
            "min": 1,
            "default": 15,
            "max": 100
        },
        "threshold": {
            "type": UserInput.OPTION_TEXT,
            "help": "Similarity threshold",
            "tooltip": "Decimal value between 0 and 1; only words with a higher similarity score than this will be included",
            "default": "0.3"
        },
        "overlay": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Plot all models?",
            "default": True,
            "tooltip": "Plot similar words for all models? If unchecked, only similar words for the most recent model will be plotted."
        }
    }

    def process(self):
        input_words = self.parameters.get("words", "")
        if not input_words or not input_words.split(","):
            self.dataset.update_status("No input words provided, cannot look for similar words.", is_final=True)
            self.dataset.finish(0)
            return

        input_words = input_words.split(",")

        num_words = convert_to_int(self.parameters.get("num-words"), self.options["num-words"]["default"])
        try:
            threshold = float(self.parameters.get("threshold", self.options["threshold"]["default"]))
        except ValueError:
            threshold = float(self.options["threshold"]["default"])

        threshold = max(-1.0, min(1.0, threshold))
        overlay = self.parameters.get("overlay")

        # retain words that are common to all models
        staging_area = self.unpack_archive_contents(self.source_file)
        common_vocab = None
        models = {}
        self.dataset.update_status("Determining cross-model common vocabulary")
        for model_file in staging_area.glob("*.model"):
            if self.interrupted:
                shutil.rmtree(staging_area)
                raise ProcessorInterruptedException("Interrupted while processing word2vec models")

            model = KeyedVectors.load(str(model_file))
            models[str(model_file)] = model

            if common_vocab is None:
                common_vocab = set(model.vocab.keys())
            else:
                common_vocab &= set(model.vocab.keys())

        # sort common vocabulary by combined frequency across all models
        common_vocab = list(common_vocab)
        common_vocab.sort(key=lambda w: sum([model.vocab[w].count for model in models.values()]), reverse=True)

        staging_area = self.unpack_archive_contents(self.source_file)

        # initialise t-sne transformer
        # use t-SNE to reduce the vectors to two-dimensionality which then makes
        # them suitable for plotting
        # parameters taken from Hamilton et al.
        # https://github.com/williamleif/histwords/blob/master/viz/common.py
        tsne = TSNE(n_components=2, random_state=0, learning_rate=150, init="pca")

        # initial boundaries of 2D space (to be adjusted later based on t-sne
        # outcome)
        max_x = 0.0 - sys.float_info.max
        max_y = 0.0 - sys.float_info.max
        min_x = sys.float_info.max
        min_y = sys.float_info.max

        # for each model, find the words that should be plotted - these are the
        # nearest neighbours for the given query words
        plottable_words = {}
        vectors = None

        # the vectors need to be reduced all at once - but the vectors are
        # grouped by model. To solve this, keep one numpy array of vectors,
        # but also keep track of which indexes of this array belong to which
        # model
        vector_indexes_first = {}
        vector_indexes_last = {}

        # now process each model
        for model_file in staging_area.glob("*.model"):
            model = KeyedVectors.load(str(model_file))
            model_name = model_file.stem

            if vectors is None:
                # can only be initialised here since now we know the vector size
                vectors = numpy.empty((0, model.vector_size))

            plottable_words[model_name] = []  # not a set, since order needs to be preserved
            self.dataset.update_status("Finding similar words in model '%s'" % model_name)

            vector_indexes_first[model_name] = len(vectors)
            vector_indexes_last[model_name] = len(vectors)

            for query in input_words:
                if self.interrupted:
                    shutil.rmtree(staging_area)
                    raise ProcessorInterruptedException("Interrupted while finding similar words")

                context = [word[0] for word in model.most_similar(query, topn=1000) if
                           word[0] in common_vocab and word[1] >= threshold][:num_words]
                context.append(query)

                # add words not seen yet to the list of words and positions to
                # plot for this model - so for all queries, all similar words
                # needed are included exactly once
                for word in context:
                    if word not in plottable_words[model_name]:
                        plottable_words[model_name].append(word)
                        vectors = numpy.append(vectors, [model[word]], axis=0)
                        vector_indexes_last[model_name] = len(vectors)

        # reduce the vectors of all words to be plotted for this model to
        # a two-dimensional coordinate with the previously initialised tsne
        # transformer
        # also keep track of the boundaries of our 2D space, so we can plot
        # them properly later
        vectors = tsne.fit_transform(vectors)
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
        colours = ["#698dcc", "#acb838", "#7665cc", "#5db645", "#c155ba", "#5bbe7d", "#cc4670", "#4ebdb0", "#d64f35",
                   "#407c45", "#be73a8", "#96a151", "#a55538", "#d49837", "#e08f75", "#7f6c29"]
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
                journeys[query].append(vectors[vector_indexes_first[model_name] + index])

        # font sizes proportional to width (which is static and thus predictable)
        fontsize_large = width / 50
        fontsize_normal = width / 75
        fontsize_small = width / 100

        # now we have the dimensions, the canvas can be instantiated
        canvas = Drawing(str(self.dataset.get_results_path()),
                         size=(width, height),
                         style="font-family:monospace;font-size:%ipx" % fontsize_normal)

        # use colour-coded backgrounds to distinguish the query words in the
        # graph
        for model_name in plottable_words:
            solid = Filter(id="solid-%s" % model_name)
            solid.feFlood(flood_color=colours[colour_index])
            solid.feComposite(in_="SourceGraphic")
            canvas.defs.add(solid)
            colour_index += 1

        # draw border
        canvas.add(Rect(
            insert=(0, 0),
            size=(width, height),
            stroke="#000",
            stroke_width=2,
            fill="#FFF"
        ))

        # header
        header = SVG(insert=(0, 0), size=("100%", fontsize_large * 2))
        header.add(Rect(insert=(0, 0), size=("100%", "100%"), fill="#000"))
        header.add(Text(
            insert=("50%", "50%"),
            text="word2vec nearest neighbours - '%s'" % ", ".join(input_words),
            dominant_baseline="middle",
            text_anchor="middle",
            fill="#FFF",
            style="font-size:%i" % fontsize_large
        ))
        canvas.add(header)

        # now plot each word for each model
        self.dataset.update_status("Plotting graph")
        words = SVG(insert=(0, 0), size=(width, height))
        last_model = max(list(plottable_words.keys()))
        colour_index = 0

        for model_name, labels in plottable_words.items():
            positions = vectors[vector_indexes_first[model_name]:vector_indexes_last[model_name]]

            label_index = 0
            print(labels)
            for position in positions:
                print(label_index)
                word = labels[label_index]
                label_index += 1

                if not overlay and model_name != last_model and word not in input_words:
                    # if we're only plotting the latest model, ignore words
                    # from other models that aren't a query
                    continue

                filter = "none" if word not in input_words else "url(#solid-%s)" % model_name
                colour = colours[colour_index] if word not in input_words else "#FFF"
                fontsize = fontsize_small if word not in input_words else fontsize_normal

                if word in input_words:
                    word += " (" + model_name + ")"

                label_container = SVG(
                    insert=position,
                    size=(1, 1), overflow="visible")
                label_container.add(Text(
                    insert=("50%", "50%"),
                    text=word,
                    dominant_baseline="middle",
                    text_anchor="middle",
                    style="fill:%s;font-size:%ipx" % (colour, fontsize),
                    filter=filter
                ))

                words.add(label_container)

            colour_index = 0 if colour_index >= len(colours) else colour_index + 1

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

        # 4cat logo
        label = "made with 4cat - 4cat.oilab.nl"
        footersize = (fontsize_small * len(label) * 0.7, fontsize_small * 2)
        footer = SVG(insert=(width - footersize[0], height - footersize[1]), size=footersize)
        footer.add(Rect(insert=(0, 0), size=("100%", "100%"), fill="#000"))
        footer.add(Text(
            insert=("50%", "50%"),
            text=label,
            dominant_baseline="middle",
            text_anchor="middle",
            fill="#FFF",
            style="font-size:%i" % fontsize_small
        ))
        canvas.add(footer)

        canvas.save(pretty=True)
        shutil.rmtree(staging_area)
        self.dataset.finish(len(journeys))
