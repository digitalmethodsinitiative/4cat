"""
Generate text embeddings via a configured LLM server.
"""
import json
import time

from datetime import datetime

from backend.lib.processor import BasicProcessor
from common.lib.compatibility import Compatibility
from common.lib.exceptions import LLMServerException, ProcessorInterruptedException, QueryParametersException
from common.lib.item_mapping import MappedItem
from common.lib.llm.llm_client import LLMServerClient, get_model_library
from common.lib.user_input import UserInput

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


class GenerateTextEmbeddings(BasicProcessor):
    """
    Generate an embedding vector per dataset item using an embedding model
    hosted on a configured LLM server.
    """
    type = "text-embeddings"  # job type ID
    category = "Text analysis"  # category
    title = "Generate text embeddings"  # title displayed in UI
    description = ("Generate a numerical representation (an 'embedding') of the text of each item using an LLM embedding "
                   "model. Embeddings can be used to e.g. map, cluster, and retrieve similar kinds of texts. Requires "
                   "an embedding model to be installed on this server.")
    extension = "ndjson"  # extension of result file, used internally and in UI

    compatibility = Compatibility(extensions={"csv", "ndjson"})

    #: Hard-coded label the embeddings are written back under, when saved as
    #: annotations. Not user-editable: a vector is only meaningful next to the
    #: model that produced it, so a free-form label invites mismatched columns.
    annotation_label = "text embedding"
    #: How many annotations to buffer before writing them to the database
    annotation_batch_size = 100

    references = [
        "[Ollama embedding models](https://ollama.com/blog/embedding-models)",
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
    def is_compatible_with(cls, module=None, config=None):
        """
        Text datasets, but only where an embedding model is actually available.

        :param module:  Dataset or processor to check against
        :param ConfigManager|None config:  Context-aware configuration reader
        :return bool:
        """
        if config is None or not cls.compatibility.is_compatible_with(module, config=config):
            return False

        return bool(get_model_library(config, task="embed"))

    @classmethod
    def get_options(cls, parent_dataset=None, config=None) -> dict:
        """
        Get processor options

        :param parent_dataset DataSet:  An object representing the dataset that
            the processor would be or was run on.
        :param config ConfigManager|None config:  Configuration reader (context-aware)
        :return dict:   Options for this processor
        """
        options = {
            "model": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Embedding model",
                # embedding models only - a generative model cannot return a vector
                "options": get_model_library(config, task="embed") if config else {},
                "default": "",
                "tooltip": "Only models that can produce embeddings are listed. Ask an admin to enable more via the "
                           "control panel.",
            },
            "columns": {
                "type": UserInput.OPTION_TEXT,
                "help": "Column(s) to embed",
                "default": "body",
                "inline": True,
                "tooltip": "Values of multiple columns are joined with a newline before being embedded.",
            },
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "help": "No. of items",
                "default": 100,
                "min": 0,
                "coerce_type": int,
                "tooltip": "Use '0' to embed all items. Embedding is slower than it looks for large datasets; test on "
                           "a sample first.",
            },
            "batch_size": {
                "type": UserInput.OPTION_TEXT,
                "help": "Items per request",
                "default": 50,
                "min": 1,
                "max": 500,
                "coerce_type": int,
                "tooltip": "How many items to send to the server at once. Higher is faster but uses more memory on the "
                           "server; lower this if requests time out.",
            },
            "save_annotations": {
                "type": UserInput.OPTION_ANNOTATION,
                # must match the label the annotations are written under, below:
                # the form renders this as "Add <label> as annotations", so a
                # different string here promises a column that never appears
                "label": cls.annotation_label,
                "tooltip": "Add embeddings as annotations to the parent dataset.",
                "default": False,
                "hide_in_explorer": True
            },
        }

        if parent_dataset and parent_dataset.get_columns():
            columns = parent_dataset.get_columns()
            options["columns"]["type"] = UserInput.OPTION_MULTI
            options["columns"]["options"] = {v: v for v in columns}
            options["columns"]["default"] = ["body"] if "body" in columns else [columns[0]]

        return options

    @classmethod
    def validate_query(cls, query, request, config):
        """
        Validate input

        :param dict query:  Query parameters, as submitted by the user via the web interface
        :param request:  Flask request
        :param ConfigManager config:  Configuration reader
        :return dict:  Validated query parameters
        """
        allowed_models = {
            model_id
            for server_models in get_model_library(config, task="embed").values()
            for model_id in server_models
        }

        if query.get("model") not in allowed_models:
            raise QueryParametersException(f"The '{query.get('model')}' embedding model is not currently available.")

        if not query.get("columns"):
            raise QueryParametersException("You need to select at least one column to embed.")

        return query

    def process(self):
        """
        Embed the text of each item and write one vector per item.
        """
        columns = self.parameters.get("columns", [])
        if isinstance(columns, str):
            columns = [columns]

        model_id = self.parameters.get("model")
        available_models = {
            k: v for k, v in self.config.get("llm.available_models", {}).items()
            if k in self.config.get("llm.enabled_models", [])
        }

        if model_id not in available_models:
            self.dataset.finish_with_error(f"Embedding model '{model_id}' is no longer available. Ask an admin to "
                                           f"enable it, or pick another model.")
            return

        model = available_models[model_id]
        server = self.config.get("llm.servers", {}).get(model["server"])
        if not server:
            self.dataset.finish_with_error(f"The LLM server for model '{model_id}' is no longer configured.")
            return

        try:
            client = LLMServerClient.get_client(self.config, server, self.log)
        except ValueError as e:
            self.dataset.finish_with_error(str(e))
            return

        limit = self.parameters.get("amount", 100)
        max_processed = min(limit, self.source_dataset.num_rows) if limit else self.source_dataset.num_rows
        batch_size = self.parameters.get("batch_size", 50)

        self.dataset.update_status(f"Connecting to LLM server '{server['_id']}' with model '{model['local_id']}'")
        self.dataset.log(f"Embedding with model '{model['local_id']}' on server '{server['_id']}'")

        self.save_annotations_enabled = self.parameters.get("save_annotations", False)
        self.annotations = []

        embedded = 0
        skipped = 0
        processed = 0
        batch = []  # (item ID, text) tuples awaiting a request

        try:
            with self.dataset.get_results_path().open("w", encoding="utf-8") as outfile:
                for item in self.source_dataset.iterate_items(self):
                    if self.interrupted:
                        raise ProcessorInterruptedException("Interrupted while generating embeddings")

                    if processed >= max_processed:
                        break

                    processed += 1

                    text = "\n".join([str(item.get(column, "")) for column in columns]).strip()
                    if not text:
                        # nothing to embed; an all-zero vector would be
                        # indistinguishable from a real one, so leave the item out
                        skipped += 1
                        continue

                    batch.append((item.get("id"), text))
                    if len(batch) < batch_size:
                        continue

                    embedded += self.embed_batch(client, model, batch, outfile)
                    batch = []
                    self.dataset.update_status(f"Embedded {embedded:,} of {max_processed:,} items with "
                                               f"{model['local_id']}")
                    self.dataset.update_progress(processed / max_processed)

                # Whatever is left over after the loop: the last batch is rarely
                # full, and the final item may have been skipped for having no
                # text, which would otherwise strand the batch it sits behind.
                embedded += self.embed_batch(client, model, batch, outfile)

            self.flush_annotations(force=True)

        except LLMServerException as e:
            # the vectors already written are still good, and so are their
            # annotations; losing them would mean redoing the whole run
            self.flush_annotations(force=True)
            if embedded:
                self.dataset.finish_with_warning(embedded, f"Not all items were embedded: {e}")
            else:
                self.dataset.finish_with_error(str(e))
            return

        if not embedded:
            self.dataset.finish_with_error("No items could be embedded; check whether the selected columns contain "
                                           "text.")
            return

        status = f"Generated embeddings for {embedded:,} items"
        if skipped:
            status += f" (skipped {skipped:,} items with no text in the selected columns)"
        self.dataset.update_status(status, is_final=True)
        self.dataset.finish(embedded)

    def flush_annotations(self, force: bool = False) -> None:
        """
        Write buffered annotations to the database.

        Buffered rather than collected until the end: a large dataset would
        otherwise hold every vector in memory a second time over, and lose the
        pending annotations entirely if the run is interrupted.

        Hidden in the Explorer - a vector is data for computation, not something
        a reader can make sense of next to a post.

        :param bool force:  Write whatever is buffered, however little.
        """
        if not self.annotations:
            return

        if force or len(self.annotations) >= self.annotation_batch_size:
            self.save_annotations(self.annotations, hide_in_explorer=True)
            self.annotations = []

    def embed_batch(self, client, model, batch, outfile) -> int:
        """
        Embed one batch of items and write the vectors to the result file.

        :param LLMServerClient client:  Client for the server hosting the model
        :param dict model:  Model metadata, as in `llm.available_models`
        :param list batch:  List of `(item ID, text)` tuples
        :param outfile:  Open file handle to write NDJSON lines to
        :return int:  Number of items written
        """
        if not batch:
            return 0

        vectors = client.embed(model["local_id"], [text for _, text in batch])

        time_created = int(time.time())
        for (item_id, text), vector in zip(batch, vectors):
            outfile.write(json.dumps({
                "id": item_id,
                "text": text,
                "embedding": vector,
                "dimensions": len(vector),
                "model": model["local_id"],
                "time_created": datetime.fromtimestamp(time_created).strftime("%Y-%m-%d %H:%M:%S"),
                "time_created_utc": time_created,
            }) + "\n")

            if self.save_annotations_enabled:
                # a text item is already one post, so its own id is what the
                # annotation attaches to - unlike media, where the file is named
                # after a hash and has to be looked up in .metadata.json
                self.annotations.append({
                    "item_id": item_id,
                    "label": self.annotation_label,
                    "value": " ".join([str(value) for value in vector]),
                    "type": "text",
                })

        # written and flushed per batch so an interrupted run keeps its results
        outfile.flush()
        self.flush_annotations()

        return len(batch)

    @staticmethod
    def map_item(item):
        """
        Map an embedding record to a flat row.

        The vector is written as space-separated values, the same shape word2vec
        and GloVe use in their text format, so the CSV export stays readable by
        other tooling.

        :param item:  Item to map
        :return MappedItem:  Mapped item
        """
        embedding = item.get("embedding", [])

        return MappedItem({
            "id": item.get("id"),
            "text": item.get("text"),
            "model": item.get("model"),
            "dimensions": item.get("dimensions"),
            "embedding": " ".join([str(value) for value in embedding]),
            "timestamp": item.get("time_created"),
        })
