"""
Generate multiple area graphs and project them isometrically
"""
import shutil
import numpy
import csv

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
        "[William L. Hamilton, Jure Leskovec, and Dan Jurafsky. ACL 2016. Diachronic Word Embeddings Reveal Statistical Laws of Semantic Change. ](https://arxiv.org/pdf/1605.09096.pdf)"
        "[William L. Hamilton, Jure Leskovec, and Dan Jurafsky. HistWords: Word Embeddings for Historical Text](https://nlp.stanford.edu/projects/histwords/)"
    ]

    options = {
        "words": {
            "type": UserInput.OPTION_TEXT,
            "help": "Words",
            "tooltip": "Separate with commas."
        },
        "num-words": {
            "type": UserInput.OPTION_TEXT,
            "help": "Amount of similar words",
            "min": 1,
            "default": 50,
            "max": 100
        },
        "threshold": {
            "type": UserInput.OPTION_TEXT,
            "help": "Similarity threshold",
            "tooltip": "Decimal value between 0 and 1; only words with a higher similarity score than this will be included",
            "default": "0.25"
        },
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

            # prime model for further editing
            # if we don't do this "vectors_norm" will not be available later
            try:
                model.most_similar("4cat")
            except KeyError:
                pass

        # sort common vocabulary by combined frequency across all models
        common_vocab = list(common_vocab)
        common_vocab.sort(key=lambda w: sum([model.vocab[w].count for model in models.values()]), reverse=True)

        staging_area = self.unpack_archive_contents(self.source_file)
        relevant_vocab = set()
        contexts = {}
        for query in input_words:
            for model_file in staging_area.glob("*.model"):
                if self.interrupted:
                    shutil.rmtree(staging_area)
                    raise ProcessorInterruptedException("Interrupted while determining common vocabulary")

                self.dataset.update_status(
                    "Determining words most similar to '%s' for model %s" % (query, model_file.name))
                model = KeyedVectors.load(str(model_file))
                try:
                    # take a larger sample than we need, because we may need
                    # to discard quite a few words not in the common vocabulary
                    contexts[model_file.stem] = [word for word in model.most_similar(query, topn=1000) if
                                                 word[0] in common_vocab][:num_words]
                except KeyError:
                    # query not in model for this interval - shouldn't happen...
                    continue
                model_vocab = set([word[0] for word in contexts[model_file.stem]])
                relevant_vocab |= model_vocab
                del model

        if not relevant_vocab:
            self.dataset.update_status(
                "No neighbouring words found for query. The query may not occur in the dataset frequently enough.")
            self.dataset.finish(0)
            return

        # take the most recent model as the one that determines the positions
        # of all words once plotted
        self.dataset.update_status("Reducing vector dimensions")
        last_model_file = sorted(list(staging_area.glob("*.model")), reverse=True)[0]
        model = KeyedVectors.load(str(last_model_file))
        word_vectors = numpy.empty((0, model.vector_size))
        plotted_words = []
        for word in relevant_vocab:
            word_vector = model[word]
            plotted_words.append(word)
            word_vectors = numpy.append(word_vectors, [word_vector], axis=0)

        # use t-SNE to reduce the vectors to two-dimensionality which then makes
        # them suitable for plotting
        # learning rate 500 because else words overlap quite a lot and the plot
        # becomes unreadable
        tsne = TSNE(n_components=2, random_state=0, learning_rate=500)
        positions = tsne.fit_transform(word_vectors)

        self.dataset.update_status("Plotting data to graph")
        # find boundaries of two-dimensional values
        min_x = min([position[0] for position in positions])
        max_x = max([position[0] for position in positions])
        min_y = min([position[1] for position in positions])
        max_y = max([position[1] for position in positions])

        # normalize positions to always use positive coordinates
        positions = [(position[0] - min_x, position[1] - min_y) for position in positions]
        max_x -= min_x
        max_y -= min_y

        # proportionally reposition within canvas space
        width = 1000
        height = width * (max_y / max_x)  # retain proportions
        scale = width / max_x
        positions = [(pos[0] * scale, pos[1] * scale) for pos in positions]

        margin = width * 0.1
        width += 2 * margin
        height += 2 * margin

        # font sizes proportional to width (which is static and thus predictable)
        fontsize_large = width / 50
        fontsize_normal = width / 75
        fontsize_small = width / 100

        # now we have the dimensions, the canvas can be instantiated
        canvas = Drawing(str(self.dataset.get_results_path()),
                         size=(width, height),
                         style="font-family:monospace;font-size:%ipx" % fontsize_normal)

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
            text="word2vec nearest neighbours - '%s'" % query,
            dominant_baseline="middle",
            text_anchor="middle",
            fill="#FFF",
            style="font-size:%i" % fontsize_large
        ))
        canvas.add(header)

        # adjust word positions for margins
        positions = [(position[0] + margin, position[1] + margin) for position in positions]

        # plot each word
        context_plot = SVG(insert=(0, 0), size=(width, height))
        for index, word in enumerate(plotted_words):
            position = positions[index]

            label_container = SVG(
                insert=position,
                size=(1, 1), overflow="visible")
            label_container.add(Text(
                insert=("50%", "50%"),
                text=word,
                dominant_baseline="middle",
                text_anchor="middle"
            ))
            context_plot.add(label_container)

        # plot the intervals (i.e. relative position of query over time)
        named_positions = {word: positions[plotted_words.index(word)] for word in plotted_words}
        journey = []
        labels = SVG(insert=(0, 0), size=(width, height))
        solid = Filter(id="solid")
        solid.feFlood(flood_color="#000")
        solid.feComposite(in_="SourceGraphic")
        labels.defs.add(solid)

        for interval, context in contexts.items():
            # calculate the position
            # this is the weighted average of all similar words found earlier
            # the average is weighted by the similarity - more similar words
            # will "pull" the query in more strongly
            x = 0
            y = 0
            combined_weight = 0
            for word in context:
                x += named_positions[word[0]][0] * word[1]
                y += named_positions[word[0]][1] * word[1]
                combined_weight += word[1]

            x /= combined_weight
            y /= combined_weight

            # save positions sequentially so we can draw arrows later
            journey.append((x, y))

            # add label for interval to SVG
            label_container = SVG(
                insert=(x, y),
                size=(1, 1), overflow="visible")
            label_container.add(Text(
                insert=("50%", "50%"),
                text=interval,
                dominant_baseline="middle",
                text_anchor="middle",
                style="fill:#FFF;font-size:%ipx" % fontsize_normal,
                filter="url(#solid)"
            ))
            labels.add(label_container)

        # draw arrows between query positions
        previous_position = None
        arrows = SVG(insert=(0, 0), size=(width, height))
        for position in journey:
            if previous_position is None:
                previous_position = position
                continue

            arrows.add(Line(start=previous_position, end=position,
                            stroke="#CE1B28", stroke_width=2))
            previous_position = position

        canvas.add(arrows)
        canvas.add(context_plot)
        canvas.add(labels)

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
        self.dataset.finish(len(journey))
