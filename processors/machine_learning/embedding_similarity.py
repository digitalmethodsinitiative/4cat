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
    title = "Compare items to a text"  # title displayed in UI
    description = ("Write a text, and score each item by how similar its meaning is to it, using the embeddings "
                   "generated for the parent dataset. Similarity is measured as cosine similarity, from -1 "
                   "(opposite) through 0 (unrelated) to 1 (identical). Because this compares meaning rather than "
                   "wording, items can score highly without sharing any words with your text.")
    extension = "csv"  # extension of result file, used internally and in UI

    compatibility = Compatibility(types={"text-embeddings"})

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
                        "different models cannot be compared.",
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
                "label": "cosine_similarity",
                "default": False,
                "tooltip": "Write the similarity score back to the original dataset as an annotation.",
            },
            "annotation_label": {
                "type": UserInput.OPTION_TEXT,
                "help": "Annotation label",
                "default": "",
                "tooltip": "[optional] Name for the annotation. Defaults to 'similarity_to_<your text>'.",
                "requires": "save_annotations==true",
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

            results.append({
                "id": item.get("id"),
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
            writer = csv.DictWriter(outfile, fieldnames=["id", "text", "similarity", "compared_to", "model"])
            writer.writeheader()
            for row in results:
                writer.writerow(row)

        if self.parameters.get("save_annotations", False):
            label = self.parameters.get("annotation_label", "").strip()
            if not label:
                # keep the label readable when the query is a long paragraph
                shortened = query_text if len(query_text) <= 20 else query_text[:20].rstrip() + "…"
                label = f"cosine_similarity_{shortened}"

            self.save_annotations([{
                "item_id": row["id"],
                "label": label,
                "value": round(row["similarity"], 4),
                "type": "text",
            } for row in results])

        status = f"Compared {len(results):,} items to your text"
        if skipped:
            status += f" (skipped {skipped:,} items without a usable embedding)"
        self.dataset.update_status(status, is_final=True)
        self.dataset.finish(len(results))
