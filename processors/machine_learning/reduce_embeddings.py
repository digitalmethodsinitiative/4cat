"""
Reduce embeddings to a chosen, smaller number of dimensions.
"""
import json

import numpy as np

from backend.lib.processor import BasicProcessor
from common.lib.compatibility import Compatibility
from common.lib.exceptions import ProcessorInterruptedException, QueryParametersException
from common.lib.item_mapping import MappedItem, value_or_missing
from common.lib.user_input import UserInput

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

#: t-SNE's default Barnes-Hut method only supports up to three dimensions; its
#: exact method goes further but scales quadratically, which is not workable at
#: the dataset sizes 4CAT deals with
TSNE_MAX_DIMENSIONS = 3


class ReduceEmbeddings(BasicProcessor):
    """
    Reduce item embeddings to N dimensions with UMAP, t-SNE or PCA.

    Kept apart from any one visualisation so the reduced coordinates are a
    result in their own right: they can be downloaded and checked, and several
    views (a 2D map, a time axis, clustering) can be built on the same reduction
    without running it again.
    """
    type = "reduce-embeddings"  # job type ID
    category = "Machine learning"  # category
    title = "Reduce dimensions of embeddings"  # title displayed in UI
    description = ("Reduce embeddings to a small number of dimensions with UMAP, t-SNE or PCA, keeping items with "
                   "similar meanings close together. Reduce to two dimensions to plot the result as a map. Note that "
                   "distances in the result may be meaningless (see references).")
    extension = "ndjson"  # extension of result file, used internally and in UI

    compatibility = Compatibility(
        types={"text-embeddings", "video-embeddings", "image-embeddings", "cluster-embeddings"},
        preferred_followups=["embedding-map", "embedding-map-3d"],
    )

    references = [
        "[McInnes, Leland, John Healy, and James Melville. 2018. 'UMAP: Uniform Manifold Approximation and Projection "
        "for Dimension Reduction.' arXiv:1802.03426.](https://arxiv.org/abs/1802.03426)",
        "[Understanding UMAP](https://pair-code.github.io/understanding-umap/)",
        "[How to Use t-SNE Effectively](https://distill.pub/2016/misread-tsne/)",
    ]

    @classmethod
    def get_options(cls, parent_dataset=None, config=None) -> dict:
        """
        Get processor options

        :param parent_dataset DataSet:  An object representing the dataset that
            the processor would be or was run on.
        :param config ConfigManager|None config:  Configuration reader (context-aware)
        :return dict:   Options for this processor
        """
        return {
            "algorithm": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Reduction algorithm",
                "options": {
                    "umap": "UMAP",
                    "tsne": "t-SNE",
                    "pca": "PCA",
                },
                "default": "umap",
                "tooltip": "UMAP keeps both local and global structure and is usually the most readable. t-SNE "
                           "separates local clusters sharply but its global layout means little, and reduces to at "
                           f"most {TSNE_MAX_DIMENSIONS} dimensions. PCA is fast and fully deterministic, but flattens "
                           "subtle structure.",
            },
            "dimensions": {
                "type": UserInput.OPTION_TEXT,
                "help": "Dimensions",
                "default": 2,
                "min": 1,
                "max": 100,
                "coerce_type": int,
                "tooltip": "Number of dimensions to reduce to. Use 2 to plot the result as a map. Higher values keep "
                           f"more structure, for example for clustering. t-SNE supports at most {TSNE_MAX_DIMENSIONS}.",
            },
            "n_neighbors": {
                "type": UserInput.OPTION_TEXT,
                "help": "UMAP: neighbours",
                "default": 15,
                "min": 2,
                "max": 200,
                "coerce_type": int,
                "tooltip": "How much of the dataset each point is compared against. Low values emphasise small local "
                           "clusters, high values emphasise overall shape.",
                "requires": "algorithm==umap",
            },
            "min_dist": {
                "type": UserInput.OPTION_TEXT,
                "help": "UMAP: minimum distance",
                "default": 0.1,
                "min": 0.0,
                "max": 0.99,
                "coerce_type": float,
                "tooltip": "How tightly points may be packed together. Lower values give denser clumps.",
                "requires": "algorithm==umap",
            },
            "perplexity": {
                "type": UserInput.OPTION_TEXT,
                "help": "t-SNE: perplexity",
                "default": 30,
                "min": 2,
                "max": 100,
                "coerce_type": int,
                "tooltip": "Roughly how many neighbours each point is balanced against. Lowered automatically if the "
                           "dataset is too small.",
                "requires": "algorithm==tsne",
            },
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "help": "No. of items",
                "default": 2000,
                "min": 0,
                "coerce_type": int,
                "tooltip": "Use '0' for all items. Reduction slows down sharply on very large datasets.",
            },
        }

    @classmethod
    def validate_query(cls, query, request, config):
        """
        Validate input

        :param dict query:  Query parameters, as submitted by the user via the web interface
        :param request:  Flask request
        :param ConfigManager config:  Configuration reader
        :return dict:  Validated query parameters
        """
        try:
            dimensions = int(query.get("dimensions", 2))
        except (TypeError, ValueError):
            raise QueryParametersException("The number of dimensions must be a whole number.")

        if query.get("algorithm") == "tsne" and dimensions > TSNE_MAX_DIMENSIONS:
            raise QueryParametersException(f"t-SNE can reduce to at most {TSNE_MAX_DIMENSIONS} dimensions. Choose "
                                           f"fewer dimensions, or use UMAP or PCA.")

        return query

    def reduce(self, vectors, dimensions):
        """
        Reduce vectors to the requested number of dimensions.

        Imports are deliberately local: `ModuleCollector` imports every
        processor at startup, and importing UMAP pulls in numba, whose JIT setup
        makes that noticeably slower for a module most installs never run.

        :param vectors:  2D numpy array of embeddings, one row per item
        :param int dimensions:  Number of dimensions to reduce to
        :return:  2D numpy array with one row of `dimensions` coordinates per item
        """
        algorithm = self.parameters.get("algorithm", "umap")
        point_count = len(vectors)

        if algorithm == "pca":
            from sklearn.decomposition import PCA
            return PCA(n_components=dimensions, random_state=42).fit_transform(vectors)

        if algorithm == "tsne":
            from sklearn.manifold import TSNE
            # perplexity must stay below the item count or sklearn refuses to run
            perplexity = min(self.parameters.get("perplexity", 30), max(2.0, (point_count - 1) / 3))
            self.dataset.log(f"Running t-SNE with perplexity {perplexity}")
            return TSNE(n_components=dimensions, perplexity=perplexity, metric="cosine", init="pca",
                        random_state=42).fit_transform(vectors)

        import umap
        # n_neighbors cannot exceed the number of other points available
        n_neighbors = min(self.parameters.get("n_neighbors", 15), point_count - 1)
        min_dist = self.parameters.get("min_dist", 0.1)
        self.dataset.log(f"Running UMAP with n_neighbors={n_neighbors}, min_dist={min_dist}")

        # cosine is the metric embeddings are meant to be compared under, and a
        # fixed random_state keeps the result reproducible - 4CAT results should
        # be retraceable, which a different layout on every run would undermine
        return umap.UMAP(n_components=dimensions, n_neighbors=n_neighbors, min_dist=min_dist, metric="cosine",
                         random_state=42).fit_transform(vectors)

    def process(self):
        """
        Read the embeddings, reduce them, and write one record per item.
        """
        limit = self.parameters.get("amount", 2000)
        max_processed = min(limit, self.source_dataset.num_rows) if limit else self.source_dataset.num_rows
        algorithm = self.parameters.get("algorithm", "umap")
        dimensions = self.parameters.get("dimensions", 2)

        if algorithm == "tsne" and dimensions > TSNE_MAX_DIMENSIONS:
            # validate_query already refuses this, but a job queued some other
            # way (e.g. via the API) should still fail with a readable message
            self.dataset.finish_with_error(f"t-SNE can reduce to at most {TSNE_MAX_DIMENSIONS} dimensions.")
            return

        vectors = []
        records = []
        source_dimensions = None

        self.dataset.update_status("Reading embeddings")
        for item in self.source_dataset.iterate_items(self):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while reading embeddings")

            if len(vectors) >= max_processed:
                break

            # the mapped item flattens the vector to a space-separated string;
            # the original NDJSON record keeps it as a list
            original = item.original
            vector = original.get("embedding")
            if isinstance(vector, str):
                vector = [float(value) for value in vector.split() if value]

            if not vector:
                continue

            if source_dimensions is None:
                source_dimensions = len(vector)
            elif len(vector) != source_dimensions:
                # a ragged matrix cannot be reduced; this means the dataset mixes
                # models, which should not happen but is worth saying out loud
                self.dataset.finish_with_error("The parent dataset contains embeddings of different sizes, so they "
                                               "cannot be reduced together.")
                return

            vectors.append(vector)

            # carry over what later steps need to label, colour and trace the
            # items back to their posts, but not the embedding itself
            record = {"id": original.get("id"), "text": original.get("text", "")}
            for key in ("filename", "post_ids", "cluster"):
                if key in original:
                    record[key] = original[key]
            records.append(record)

        point_count = len(vectors)
        if point_count < 3:
            self.dataset.finish_with_error(f"Not enough embeddings to reduce (found {point_count}, need at least 3).")
            return

        if dimensions >= source_dimensions:
            self.dataset.finish_with_error(f"The embeddings have {source_dimensions} dimensions, so they cannot be "
                                           f"reduced to {dimensions}.")
            return

        # UMAP's spectral initialisation and PCA both need more items than
        # dimensions; checked here rather than left to an opaque library error
        if dimensions >= point_count - 1:
            self.dataset.finish_with_error(f"Reducing to {dimensions} dimensions needs at least {dimensions + 2} "
                                           f"items; this dataset has {point_count}.")
            return

        self.dataset.update_status(f"Reducing {point_count:,} embeddings of {source_dimensions} dimensions to "
                                   f"{dimensions} with {algorithm.upper()}; this may take a while")
        coordinates = self.reduce(np.asarray(vectors, dtype=np.float32), dimensions)

        self.dataset.update_status("Writing reduced embeddings")
        with self.dataset.get_results_path().open("w", encoding="utf-8") as outfile:
            for record, row in zip(records, coordinates):
                record.update({
                    "coordinates": [round(float(value), 6) for value in row],
                    "dimensions": dimensions,
                    "source_dimensions": source_dimensions,
                    "algorithm": algorithm,
                })
                outfile.write(json.dumps(record, ensure_ascii=False) + "\n")

        self.dataset.update_status(f"Reduced {point_count:,} embeddings to {dimensions} dimensions", is_final=True)
        self.dataset.finish(point_count)

    @staticmethod
    def map_item(item):
        """
        Map a reduced embedding to a flat row, one column per dimension.

        :param item:  Item to map
        :return MappedItem:  Mapped item
        """
        mapped = {
            "id": item.get("id"),
            "text": item.get("text"),
            # only media embeddings have these
            "filename": value_or_missing(item, "filename", ""),
            "post_ids": ", ".join([str(post_id) for post_id in item.get("post_ids", [])])
            if "post_ids" in item else value_or_missing(item, "post_ids", ""),
            "algorithm": item.get("algorithm"),
            # only clustered embeddings have this
            "cluster": value_or_missing(item, "cluster", ""),
        }

        for index, value in enumerate(item.get("coordinates", []), start=1):
            mapped[f"dimension_{index}"] = value

        return MappedItem(mapped)
