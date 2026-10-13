"""
Assign each embedding to a cluster of similar items.
"""
import json
from collections import Counter

import numpy as np

from backend.lib.processor import BasicProcessor
from common.lib.compatibility import Compatibility
from common.lib.embeddings import normalise_in_place, read_embedding_matrix
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.item_mapping import MappedItem, value_or_missing
from common.lib.user_input import UserInput
from processors.machine_learning.embed_media import read_post_id_map

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

# Silhouette scores compare every point with every other, so they are
# computed on a sample of at most this many points
SILHOUETTE_SAMPLE = 5000


class ClusterEmbeddings(BasicProcessor):
    """
    Group embeddings into clusters with k-means or HDBSCAN.

    Writes the embeddings unchanged plus a `cluster` field, so that anything
    that runs on embeddings can also run on the reulst here. Clusters are numbered by size, the
    largest first; HDBSCAN's outliers are cluster -1.
    """
    type = "cluster-embeddings"  # job type ID
    category = "Machine learning"  # category
    title = "Cluster embeddings"  # title displayed in UI
    description = ("Assign clusters to embeddings using HDBSCAN or k-means.")
    extension = "ndjson"  # extension of result file, used internally and in UI

    compatibility = Compatibility(
        types={"text-embeddings", "video-embeddings", "image-embeddings"},
        preferred_followups=["reduce-embeddings"],
    )

    # Label the clusters are written under when saved as annotations
    annotation_label = "embedding cluster"

    # Annotations are saved in batches of this many while writing
    annotation_batch_size = 1000

    references = [
        "[Campello, Ricardo J. G. B., Davoud Moulavi, and Jörg Sander. 2013. 'Density-Based Clustering Based on "
        "Hierarchical Density Estimates.' PAKDD 2013.](https://doi.org/10.1007/978-3-642-37456-2_14)",
        "[How HDBSCAN works](https://hdbscan.readthedocs.io/en/latest/how_hdbscan_works.html)",
        "[scikit-learn: k-means](https://scikit-learn.org/stable/modules/clustering.html#k-means)",
        "[scikit-learn: silhouette score](https://scikit-learn.org/stable/modules/clustering.html#silhouette-coefficient)",
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
                "help": "Clustering algorithm",
                "options": {
                    "hdbscan": "HDBSCAN (finds the number of clusters)",
                    "kmeans": "K-means (a set number of clusters)",
                },
                "default": "hdbscan",
                "tooltip": "HDBSCAN finds clusters of any shape, decides how many there are, and assigns items that "
                           "fit nowhere a 'noise' cluster -1. K-means puts every item in one of a set "
                           "number of clusters, and assumes they are round and of similar size.",
            },
            "min_cluster_size": {
                "type": UserInput.OPTION_TEXT,
                "help": "Minimum cluster size",
                "default": 10,
                "min": 2,
                "max": 10000,
                "coerce_type": int,
                "tooltip": "The smallest group HDBSCAN will call a cluster. Higher values give fewer but larger "
                           "clusters as well as more noise.",
                "requires": "algorithm==hdbscan",
            },
            "n_clusters": {
                "type": UserInput.OPTION_TEXT,
                "help": "K-means: number of clusters",
                "default": 8,
                "min": 2,
                "max": 100,
                "coerce_type": int,
                "tooltip": "How many clusters to make. With automatic choice on, use this number as the max clusters to try.",
                "requires": "algorithm==kmeans",
            },
            "auto_clusters": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Find optimal number of clusters (silhouette)",
                "default": False,
                "tooltip": "Try every number of clusters from 2 up to the number above, and keep the one with the "
                           "best silhouette score (how much closer items are to their own cluster than to the next). "
                           "All scores are written to the log.",
                "requires": "algorithm==kmeans",
            },
            "reduce_first": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Reduce with UMAP first (recommended for HDBSCAN)",
                "default": True,
                "tooltip": "Cluster on a UMAP reduction of the embeddings instead of the full vectors. HDBSCAN finds "
                           "little in vectors with hundreds or thousands of dimensions, so for HDBSCAN this is "
                           "strongly recommended; k-means usually benefits too. The reduction is only used to find "
                           "the clusters: the output keeps the full embeddings.",
            },
            "reduce_dimensions": {
                "type": UserInput.OPTION_TEXT,
                "help": "Dimensions to reduce to",
                "default": 25,
                "min": 2,
                "max": 100,
                "coerce_type": int,
                "tooltip": "Check what is recommended for k-means/HBDSCAN and test with your data.",
                "requires": "reduce_first==true",
            },
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "help": "No. of items",
                "default": 0,
                "min": 0,
                "coerce_type": int,
                "tooltip": "Use '0' for all items. Clustering on a reduction slows down on very large datasets.",
            },
            "save_annotations": {
                "type": UserInput.OPTION_ANNOTATION,
                "label": cls.annotation_label,
                "tooltip": "Add each item's cluster number as an annotation to the original dataset. Media files "
                           "annotate every post they appeared in.",
                "default": False,
            },
        }

    def process(self):
        """
        Read the embeddings, cluster them, and write them back with a cluster.

        Two passes over the embeddings: the first reads only the vectors,
        into one array; the second reads each record again to write it out
        with its cluster. Holding the records themselves in between would keep
        every vector in memory a second time, as Python numbers.
        """
        limit = self.parameters.get("amount", 0)
        max_processed = min(limit, self.source_dataset.num_rows) if limit else self.source_dataset.num_rows

        self.dataset.update_status("Reading embeddings")
        try:
            matrix, positions, _ = read_embedding_matrix(self.source_dataset, max_processed, self)
        except ValueError:
            self.dataset.finish_with_error("The parent dataset contains embeddings of different sizes, so they "
                                           "cannot be clustered together.")
            return

        point_count = len(positions)
        if point_count < 3:
            self.dataset.finish_with_error(f"Not enough embeddings to cluster (found {point_count}, need at least "
                                           f"3).")
            return

        normalise_in_place(matrix)

        if self.parameters.get("reduce_first", True):
            matrix = self.reduce(matrix)
        elif self.parameters.get("algorithm") == "hdbscan":
            self.dataset.log("Clustering the full vectors with HDBSCAN. This often finds few clusters and much noise; "
                             "reducing with UMAP first usually works better.")

        self.dataset.update_status(f"Clustering {point_count:,} embeddings")
        clusters = self.renumber_by_size(self.cluster(matrix))
        del matrix

        sizes = Counter(clusters)
        noise = sizes.pop(-1, 0)
        summary = f"Found {len(sizes):,} clusters"
        if noise:
            summary += f" and {noise:,} items that fit no cluster"
        self.dataset.log(summary + ". Cluster sizes: " +
                         ", ".join(f"{cluster}: {size:,}" for cluster, size in sorted(sizes.items())))

        save_annotations = self.parameters.get("save_annotations", False)
        annotations = []
        post_id_map = None
        unmatched = 0

        self.dataset.update_status("Writing clustered embeddings")
        with self.dataset.get_results_path().open("w", encoding="utf-8") as outfile:
            # the second pass: the same items in the same order, so the
            # positions from the first pass say which row each one is
            row = 0
            for position, item in enumerate(self.source_dataset.iterate_items(self, get_annotations=False)):
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while writing clustered embeddings")
                if row == point_count:
                    break
                if position != positions[row]:
                    continue

                # a copy, so adding the cluster leaves the item itself alone
                record = dict(item.original)
                record["cluster"] = int(clusters[row])
                row += 1
                outfile.write(json.dumps(record, ensure_ascii=False) + "\n")

                if not save_annotations:
                    continue

                # media files are named after a hash that matches no post; the
                # posts they appeared in come from the record or the archive
                post_ids = self.get_post_ids(record)
                if post_ids is None:
                    if post_id_map is None:
                        archive = self.source_dataset.get_parent()
                        post_id_map = read_post_id_map(archive.get_results_path() if archive else None,
                                                       log=self.dataset.log)
                    post_ids = post_id_map.get(str(record.get("id")), [])
                if not post_ids:
                    unmatched += 1

                annotations.extend({
                    "item_id": str(post_id),
                    "label": self.annotation_label,
                    "value": str(record["cluster"]),
                    "type": "text",
                } for post_id in post_ids)

                # saved in batches as we go: progress shows, and a run that
                # fails halfway keeps what it saved
                if len(annotations) >= self.annotation_batch_size:
                    self.save_annotations(annotations)
                    annotations = []
                    self.dataset.update_status(f"Writing clustered embeddings and annotations ({row:,}/"
                                               f"{point_count:,})")

        if annotations:
            self.save_annotations(annotations)
        if unmatched:
            self.dataset.log(f"{unmatched:,} files could not be linked to a post in the original dataset, so their "
                             f"clusters were not added as annotations.")

        self.dataset.update_status(summary, is_final=True)
        self.dataset.finish(point_count)

    @staticmethod
    def get_post_ids(record: dict) -> list | None:
        """
        Get the posts in the original dataset an embedding stands for.

        A text embedding's ID is its post's ID. A media file's ID is a hash of
        the file, which matches no post: it stands for the posts it appeared
        in. Embeddings made before those were always recorded lack them.

        :param dict record:  Embedding record
        :return list|None:  Post IDs, or `None` for a media file whose posts
          were not recorded and have to be looked up in the archive
        """
        if "filename" not in record:
            return [record.get("id")]
        return record.get("post_ids") or None

    def reduce(self, matrix):
        """
        Reduce the embeddings with UMAP, only to find clusters in.

        Settings follow BERTopic's: `min_dist` 0 packs similar items tightly,
        which is what a clustering algorithm needs, rather than what a readable
        map needs.

        :param matrix:  2D numpy array, one normalised embedding per row
        :return:  2D numpy array with the reduced vectors
        """
        import umap

        point_count, dimensions = matrix.shape
        target = min(self.parameters.get("reduce_dimensions", 5), dimensions - 1, point_count - 2)
        self.dataset.update_status(f"Reducing {point_count:,} embeddings to {target} dimensions with UMAP before "
                                   f"clustering; this may take a while")
        self.dataset.log(f"Reducing to {target} dimensions with UMAP (cosine, n_neighbors=15, min_dist=0.0) before "
                         f"clustering")

        # fixed random_state: the same input should give the same clusters
        return umap.UMAP(n_components=target, n_neighbors=min(15, point_count - 1), min_dist=0.0, metric="cosine",
                         random_state=42).fit_transform(matrix)

    def cluster(self, matrix) -> np.ndarray:
        """
        Run the chosen clustering algorithm.

        :param matrix:  2D numpy array, one (normalised or reduced) vector per row
        :return:  Cluster label per row; -1 for HDBSCAN's noise
        """
        point_count = len(matrix)

        if self.parameters.get("algorithm", "hdbscan") == "kmeans":
            from sklearn.cluster import KMeans

            most = min(self.parameters.get("n_clusters", 8), point_count - 1)
            if not self.parameters.get("auto_clusters"):
                self.dataset.log(f"Running k-means with {most} clusters")
                return KMeans(n_clusters=most, n_init="auto", random_state=42).fit_predict(matrix)

            from sklearn.metrics import silhouette_score

            best_score, best_labels = None, None
            for count in range(2, most + 1):
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while choosing the number of clusters")

                self.dataset.update_status(f"Trying {count} of up to {most} clusters")
                labels = KMeans(n_clusters=count, n_init="auto", random_state=42).fit_predict(matrix)
                score = silhouette_score(matrix, labels, sample_size=min(point_count, SILHOUETTE_SAMPLE),
                                         random_state=42)
                self.dataset.log(f"{count} clusters: silhouette score {score:.3f}")
                if best_score is None or score > best_score:
                    best_score, best_labels = score, labels

            self.dataset.log(f"Chose {len(set(best_labels))} clusters (silhouette score {best_score:.3f})")
            return best_labels

        from sklearn.cluster import HDBSCAN

        min_cluster_size = min(self.parameters.get("min_cluster_size", 10), point_count)
        self.dataset.log(f"Running HDBSCAN with a minimum cluster size of {min_cluster_size}")
        # copy=False: the matrix is not used again, so no need to hold it twice
        return HDBSCAN(min_cluster_size=min_cluster_size, copy=False).fit_predict(matrix)

    @staticmethod
    def renumber_by_size(labels) -> list:
        """
        Number clusters by size, the largest 0, keeping noise at -1.

        The algorithms number clusters arbitrarily. By size, the numbers mean
        something, and plots can give the largest clusters the clearest colours.

        :param labels:  Cluster label per item
        :return list:  New cluster number per item
        """
        sizes = Counter(int(label) for label in labels if label != -1)
        order = {label: rank for rank, (label, _) in enumerate(sorted(sizes.items(), key=lambda kv: (-kv[1], kv[0])))}
        return [order.get(int(label), -1) for label in labels]

    @staticmethod
    def map_item(item):
        """
        Map a clustered embedding to a flat row.

        The same shape the embedding datasets map to, plus the cluster.

        :param item:  Item to map
        :return MappedItem:  Mapped item
        """
        embedding = item.get("embedding", [])

        return MappedItem({
            "id": item.get("id"),
            "text": item.get("text"),
            "cluster": item.get("cluster"),
            # only media embeddings have these
            "filename": value_or_missing(item, "filename", ""),
            "post_ids": ", ".join([str(post_id) for post_id in item.get("post_ids", [])])
            if "post_ids" in item else value_or_missing(item, "post_ids", ""),
            "model": item.get("model"),
            "dimensions": item.get("dimensions"),
            "embedding": " ".join([str(value) for value in embedding]),
            "timestamp": item.get("time_created"),
        })
