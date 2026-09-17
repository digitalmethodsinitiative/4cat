"""
Rank dataset items by how close their embedding is to a given text.
"""
import csv

import numpy as np

from backend.lib.processor import BasicProcessor
from common.lib.compatibility import Compatibility
from common.lib.exceptions import LLMServerException, ProcessorInterruptedException, QueryParametersException
from common.lib.llm.llm_client import LLMServerClient
from common.lib.user_input import UserInput
from processors.machine_learning.embed_media import read_post_id_map

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


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

    compatibility = Compatibility(types={"text-embeddings", "video-embeddings", "image-embeddings"})

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
        model_id = self.source_dataset.parameters.get("model")
        available_models = {
            k: v for k, v in self.config.get("llm.available_models", {}).items()
            if k in self.config.get("llm.enabled_models", [])
        }

        if model_id not in available_models:
            self.dataset.finish_with_error(
                f"The embedding model used for the parent dataset ('{model_id}') is no longer available, so your text "
                f"cannot be embedded in the same way. Ask an admin to re-enable it.")
            return

        model = available_models[model_id]
        server = self.config.get("llm.servers", {}).get(model["server"])
        if not server:
            self.dataset.finish_with_error(f"The LLM server for model '{model_id}' is no longer configured.")
            return

        self.dataset.update_status(f"Embedding your text with {model['local_id']}")
        try:
            client = LLMServerClient.get_client(self.config, server, self.log)
            query_vector = np.asarray(client.embed(model["local_id"], [query_text])[0], dtype=np.float64)
        except (LLMServerException, ValueError, IndexError) as e:
            self.dataset.finish_with_error(f"Could not embed your text: {e}")
            return

        query_norm = np.linalg.norm(query_vector)
        if not query_norm:
            self.dataset.finish_with_error("Your text produced an empty embedding; try a longer or different text.")
            return

        post_id_map = self.load_post_id_map()

        self.dataset.update_status("Comparing items to your text")
        results = []
        skipped = 0

        for i, item in enumerate(self.source_dataset.iterate_items(self)):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while calculating similarities")

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

            post_ids = self.resolve_post_ids(item, post_id_map)

            results.append({
                "id": item.get("id"),
                "post_ids": post_ids,
                "text": item.get("text"),
                "similarity": float(np.dot(query_vector, vector) / (query_norm * norm)),
                "compared_to": query_text,
                "model": item.get("model", model["local_id"]),
            })

            if i % 250 == 0:
                self.dataset.update_progress(i / self.source_dataset.num_rows)

        if not results:
            self.dataset.finish_with_error("No comparable embeddings were found in the parent dataset.")
            return

        if self.parameters.get("sort", True):
            results.sort(key=lambda row: row["similarity"], reverse=True)

        with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile:
            writer = csv.DictWriter(outfile, fieldnames=["id", "post_ids", "text", "similarity", "compared_to",
                                                         "model"])
            writer.writeheader()
            for row in results:
                writer.writerow({**row, "post_ids": ", ".join([str(_) for _ in row["post_ids"]])})

        if self.parameters.get("save_annotations", False):
            self.save_similarity_annotations(results, query_text)

        status = f"Compared {len(results):,} items to your text"
        if skipped:
            status += f" (skipped {skipped:,} items without a usable embedding)"
        self.dataset.update_status(status, is_final=True)
        self.dataset.finish(len(results))

    def load_post_id_map(self) -> dict:
        """
        Look up post IDs for media embeddings, via the archive they came from.

        Only media embeddings need this. A text embedding is already one post.

        :return dict:  `{filename without extension: [post ID, ...]}`
        """
        parent = self.source_dataset.get_parent()
        if not parent:
            return {}

        post_ids = read_post_id_map(parent.get_results_path(), log=self.dataset.log)
        if post_ids:
            self.dataset.log(f"Found post IDs for {len(post_ids):,} media files in .metadata.json")

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

        item_id = item.get("id")
        if item_id in post_id_map:
            return [post_id for post_id in post_id_map[item_id] if post_id]

        return [item_id] if item_id else []

    def save_similarity_annotations(self, results: list, query_text: str) -> None:
        """
        Write the scores back to the top dataset as annotations.

        :param list results:  Scored rows, each with `post_ids` and `similarity`
        :param str query_text:  The text everything was compared against
        """
        # keep the label readable when the query is a long paragraph
        shortened = query_text if len(query_text) <= 20 else query_text[:20].rstrip() + "…"
        label = f"cosine similarity to '{shortened}'"

        annotations = []
        saved = 0
        for row in results:
            # a media file can belong to several posts, and each gets the score
            for post_id in row["post_ids"]:
                if not post_id:
                    continue
                annotations.append({
                    "item_id": post_id,
                    "label": label,
                    "value": round(row["similarity"], 4),
                    "type": "text",
                })

            if len(annotations) >= self.annotation_batch_size:
                saved += self.save_annotations(annotations)
                annotations = []

        if annotations:
            saved += self.save_annotations(annotations)

        self.dataset.update_status(f"Saved {saved:,} similarity annotations to the top dataset")
