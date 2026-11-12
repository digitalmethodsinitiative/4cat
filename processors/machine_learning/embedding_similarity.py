"""
Rank dataset items by how close their embedding is to a given text (embedding).
"""
import csv
import json

from array import array

import numpy as np

from backend.lib.processor import BasicProcessor
from common.lib.compatibility import Compatibility
from common.lib.embeddings import amount_option, items_to_read
from common.lib.exceptions import LLMServerException, ProcessorInterruptedException, QueryParametersException
from common.lib.llm.llm_client import LLMServerClient, resolve_model
from common.lib.user_input import UserInput

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

# Embeddings with a cluster per item; the model and media archive belong to
# the embeddings dataset above them
CLUSTERED_EMBEDDINGS = "cluster-embeddings"


def embed_query(config, model_id: str, text: str, log=None) -> tuple:
    """
    Embed a text with the model a set of embeddings was made with.

    The text has to be embedded by the same model that produced the vectors
    it is compared with: vectors from different models live in different
    spaces, so comparing them yields a number that means nothing.

    :param config:  4CAT config reader
    :param str model_id:  ID of the model the embeddings were made with
    :param str text:  Text to embed
    :param log:  Logger, passed on to the LLM client
    :return tuple:  `(vector, model entry, None)` on success, or
      `(None, None, error message)`
    """
    model, server, error = resolve_model(config, model_id, task="embed")
    if error:
        return None, None, (f"The embedding model used for the parent dataset ('{model_id}') is not available to you, "
                            f"so your text cannot be embedded in the same way. {error}")

    try:
        client = LLMServerClient.get_client(config, server, log)
        vector = np.asarray(client.embed(model["local_id"], [text])[0], dtype=np.float64)
    except (LLMServerException, ValueError, IndexError) as e:
        return None, None, f"Could not embed your text: {e}"

    if not np.linalg.norm(vector):
        return None, None, "Your text produced an empty embedding; try a longer or different text."

    return vector, model, None


class EmbeddingSimilarity(BasicProcessor):
    """
    Embed a user-supplied text with the same model the parent dataset used, then
    score every item by the cosine similarity between the two vectors.
    """
    type = "embedding-similarity"  # job type ID
    category = "Text analysis"  # category
    title = "Calculate cosine similarity with text embedding"  # title displayed in UI
    description = ("Calculate the similarity between each embedding of the parent dataset and a self-inserted text. "
                   "Similarity is measured as cosine similarity, from -1 (opposite) to 1 (identical).")
    extension = "csv"  # extension of result file, used internally and in UI

    compatibility = Compatibility(types={"text-embeddings", "video-embeddings", "image-embeddings",
                                         "cluster-embeddings"})

    annotation_batch_size = 100

    references = [
        "[Cosine similarity](https://en.wikipedia.org/wiki/Cosine_similarity)",
    ]

    @classmethod
    def get_queue_id(cls, remote_id, details, dataset) -> str:
        """
        Shared queue for locally hosted models

        :param str remote_id:  Job item ID
        :param dict details:  Job details
        :param DataSet dataset:  Dataset to run job for
        :return str:  Queue ID
        """
        # Unique queue for locally hosted models; used by other local model processors as well
        return "local_models"

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
            "query_info": {
                "type": UserInput.OPTION_INFO,
                "help": "Your text is embedded with the same model the parent dataset used, since vectors from "
                        "different models cannot be compared. When the parent contains video embeddings and the "
                        "model is multimodal, this searches the videos by description.",
            },
            "query_text": {
                "type": UserInput.OPTION_TEXT_LARGE,
                "help": "Text to compare against",
                "default": "",
                "tooltip": "A word, sentence, or paragraph. Longer texts describing a theme usually work better "
                           "than single words.",
            },
            "sort": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Sort by similarity",
                "default": True,
                "tooltip": "Put the most similar items first. Disable to keep the original order of the dataset.",
            },
            "amount": amount_option(config, "Every item is scored and written out, and with annotations on, each one "
                                            "also becomes a row in the database."),
            "save_annotations": {
                "type": UserInput.OPTION_ANNOTATION,
                # the written label folds in the query text, which is not known
                # until the run; this is the readable stem of it
                "label": "cosine similarity",
                "default": False,
                "tooltip": "Add cosine similarities as annotations to the top dataset.",
            }
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
        if not query.get("query_text", "").strip():
            raise QueryParametersException("You need to provide a text to compare against.")

        return query

    def process(self):
        """
        Score each item by cosine similarity to the embedded query text.
        """
        query_text = self.parameters.get("query_text", "").strip()

        # The query has to be embedded by the same model that produced the
        # parent's vectors - vectors from different models live in different
        # spaces, so comparing them yields a number that means nothing.
        embeddings = self.get_embeddings_dataset()
        model_id = embeddings.parameters.get("model") if embeddings else None

        self.dataset.update_status(f"Embedding your text with {model_id}")
        query_vector, model, error = embed_query(self.config, model_id, query_text, log=self.log)
        if error:
            self.dataset.finish_with_error(error)
            return

        query_norm = np.linalg.norm(query_vector)

        post_id_map = self.load_post_id_map()
        max_items = items_to_read(self.parameters, self.config, self.source_dataset.num_rows)

        fieldnames = ["id", "post_ids", "text", "similarity", "compared_to", "model"]
        if self.source_dataset.type == CLUSTERED_EMBEDDINGS:
            fieldnames.append("cluster")

        self.annotation_label = self.similarity_label(query_text)
        self.annotations = []
        self.save_annotations_enabled = self.parameters.get("save_annotations", False)

        scored = self.score_items(query_vector, query_norm, query_text, model, post_id_map, max_items, fieldnames)
        if not scored:
            self.dataset.finish_with_error("No comparable embeddings were found in the parent dataset.")
            return

        written, skipped = scored
        self.flush_annotations(force=True)

        status = f"Compared {written:,} items to your text"
        if skipped:
            status += f" (skipped {skipped:,} items without a usable embedding)"
        self.dataset.update_status(status, is_final=True)
        self.dataset.finish(written)

    def score_items(self, query_vector, query_norm, query_text, model, post_id_map, max_items, fieldnames):
        """
        Score every item and write the rows, sorted if the user asked for that.

        Sorting needs every score before the first row can be written, but not
        every row: the rows go to a scratch file as they are scored, and only
        each one's score and its offset in that file are held in memory. That
        is 16 bytes an item, rather than its whole text.

        :param query_vector:  The embedded query
        :param float query_norm:  Its length
        :param str query_text:  The text that was embedded, written per row
        :param dict model:  Model metadata, for the fallback model name
        :param dict post_id_map:  Filenames to post IDs
        :param int max_items:  Most items to score
        :param list fieldnames:  Columns of the result file
        :return tuple|None:  `(rows written, items skipped)`, or `None` if
          nothing could be scored
        """
        rows = self.iterate_scores(query_vector, query_norm, query_text, model, post_id_map, max_items)

        if not self.parameters.get("sort", True):
            # the original order, so each row can be written as it is scored
            written, skipped = 0, 0
            with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile:
                writer = csv.DictWriter(outfile, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for row, skipped in rows:
                    if row is None:
                        continue
                    self.write_row(writer, row)
                    written += 1

            return (written, skipped) if written else None

        offsets, scores = array("q"), array("d")
        skipped = 0
        staging = self.dataset.get_staging_area()
        scratch_path = staging.joinpath("scored.ndjson")

        with scratch_path.open("w", encoding="utf-8") as scratch:
            for row, skipped in rows:
                if row is None:
                    continue
                offsets.append(scratch.tell())
                scores.append(row["similarity"])
                scratch.write(json.dumps(row, ensure_ascii=False) + "\n")

        if not offsets:
            return None

        self.dataset.update_status(f"Sorting {len(offsets):,} items by similarity")
        # stable, so that items scoring the same always come out in the order
        # they were read and the same input gives the same file twice
        order = np.argsort(-np.frombuffer(scores, dtype=np.float64), kind="stable")

        self.dataset.update_status("Writing results")
        with (self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile,
              scratch_path.open("r", encoding="utf-8") as scratch):
            writer = csv.DictWriter(outfile, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for position, index in enumerate(order):
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while writing results")

                scratch.seek(offsets[index])
                self.write_row(writer, json.loads(scratch.readline()))

                if position % 1000 == 0:
                    self.dataset.update_progress(position / len(order))

        return len(order), skipped

    def iterate_scores(self, query_vector, query_norm, query_text, model, post_id_map, max_items):
        """
        Score each item in turn, yielding one row at a time.

        :param query_vector:  The embedded query
        :param float query_norm:  Its length
        :param str query_text:  The text that was embedded
        :param dict model:  Model metadata, for the fallback model name
        :param dict post_id_map:  Filenames to post IDs
        :param int max_items:  Most items to score
        :return:  Generator of `(row or None, items skipped so far)`
        """
        self.dataset.update_status("Comparing items to your text")
        skipped = 0
        scored = 0

        for i, item in enumerate(self.source_dataset.iterate_items(self)):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while calculating similarities")

            if scored >= max_items:
                break

            vector = item.get("embedding")
            # map_item flattens the vector to a space-separated string; the raw
            # NDJSON keeps it as a list. Accept either.
            if isinstance(vector, str):
                vector = [float(value) for value in vector.split() if value]

            if not vector or len(vector) != len(query_vector):
                # a vector of a different width cannot be compared; scoring it
                # anyway would silently produce a meaningless number
                skipped += 1
                continue

            vector = np.asarray(vector, dtype=np.float64)
            norm = np.linalg.norm(vector)
            if not norm:
                skipped += 1
                continue

            scored += 1
            yield {
                "id": item.get("id"),
                "post_ids": self.resolve_post_ids(item, post_id_map),
                "text": item.get("text"),
                "similarity": float(np.dot(query_vector, vector) / (query_norm * norm)),
                "compared_to": query_text,
                "model": item.get("model", model["local_id"]),
                # only clustered embeddings have one
                "cluster": item.get("cluster", ""),
            }, skipped

            if i % 250 == 0 and self.source_dataset.num_rows:
                self.dataset.update_progress(i / self.source_dataset.num_rows)

        # a last word on how many were left out, even if nothing was scored
        yield None, skipped

    def write_row(self, writer, row: dict) -> None:
        """
        Write one row, and buffer its annotation if they were asked for.

        :param writer:  Open `csv.DictWriter`
        :param dict row:  Row to write
        """
        writer.writerow({**row, "post_ids": ", ".join([str(post_id) for post_id in row["post_ids"]])})

        if self.save_annotations_enabled:
            # a media file can belong to several posts, and each gets the score
            for post_id in row["post_ids"]:
                if not post_id:
                    continue
                self.annotations.append({
                    "item_id": post_id,
                    "label": self.annotation_label,
                    "value": round(row["similarity"], 4),
                    "type": "text",
                })

            self.flush_annotations()

    def get_embeddings_dataset(self):
        """
        Get the dataset the embeddings were made in, past any clustering step.

        Clustered embeddings carry the same vectors, but the model and the
        media archive belong to the embeddings they were made from.

        :return DataSet|None:  The embeddings dataset
        """
        dataset = self.source_dataset
        while dataset is not None and getattr(dataset, "type", None) == CLUSTERED_EMBEDDINGS:
            dataset = dataset.get_parent()
        return dataset

    def load_post_id_map(self) -> dict:
        """
        Look up post IDs for media embeddings, via the archive they came from.

        Only media embeddings need this. A text embedding is already one post.

        :return dict:  `{filename without extension: [post ID, ...]}`
        """
        embeddings = self.get_embeddings_dataset()
        parent = embeddings.get_parent() if embeddings else None
        if not parent:
            return {}

        metadata = self.get_media_metadata(parent)
        post_ids = metadata.filename_to_post_ids() if metadata else {}
        if post_ids:
            self.dataset.log(f"Found post IDs for {len(post_ids):,} media files in the archive metadata")

        return post_ids

    @staticmethod
    def resolve_post_ids(item, post_id_map: dict) -> list:
        """
        Decide which posts an embedding belongs to.

        :param item:  Embedding record from the parent dataset
        :param dict post_id_map:  Filenames to post IDs, from `.metadata.json`
        :return list:  Post IDs to attach values to
        """
        recorded = item.get("post_ids")
        if recorded:
            # map_item flattens the list to a comma-separated string; the raw
            # NDJSON keeps it a list. Accept either.
            if isinstance(recorded, str):
                return [post_id.strip() for post_id in recorded.split(",") if post_id.strip()]
            return [post_id for post_id in recorded if post_id]

        # a media file is named after its contents, so the archive says which
        # posts it came from; a text embedding's own ID is already a post's
        filename = item.get("filename")
        if filename in post_id_map:
            return [post_id for post_id in post_id_map[filename] if post_id]

        item_id = item.get("id")

        return [item_id] if item_id else []

    @staticmethod
    def similarity_label(query_text: str) -> str:
        """
        The label the scores are written back under.

        :param str query_text:  The text everything was compared against
        :return str:  Annotation label
        """
        # keep the label readable when the query is a long paragraph
        shortened = query_text if len(query_text) <= 20 else query_text[:20].rstrip() + "…"
        return f"cosine similarity to '{shortened}'"

    def flush_annotations(self, force: bool = False) -> None:
        """
        Write buffered annotations to the database.

        Buffered rather than collected until the end, so that a large dataset
        does not hold an annotation per item alongside its results.

        :param bool force:  Write whatever is buffered, however little.
        """
        if not self.annotations:
            return

        if force or len(self.annotations) >= self.annotation_batch_size:
            self.save_annotations(self.annotations)
            self.annotations = []
