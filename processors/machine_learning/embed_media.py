"""
Shared behaviour for processors that embed media files via a multimodal model.

`EmbedVideos` and `EmbedImages` differ only in how a file is made smaller before
it is sent; everything around that - resolving the model, walking the archive,
batching, writing results - is identical, and lives here.

This class is abstract (`prepare_media` has no implementation), so
`ModuleCollector` skips it: `is_4cat_class()` ignores anything
`inspect.isabstract()` reports, and also ignores classes whose `__module__` is
not the file being scanned, which covers the subclass imports.
"""
import abc
import base64
import json
import time
import zipfile

from datetime import datetime

from backend.lib.processor import BasicProcessor
from common.lib.exceptions import LLMServerException, ProcessorInterruptedException, QueryParametersException
from common.lib.item_mapping import MappedItem
from common.lib.llm.llm_client import LLMServerClient, get_model_library
from common.lib.user_input import UserInput

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


def read_post_id_map(archive_path, log=None) -> dict:
    """
    Map each media filename in an archive to the posts it was downloaded for.

    A media archive's `.metadata.json` is keyed by source URL, and each entry
    carries the `post_ids` it came from plus the `files` written for it. One
    media file can belong to several posts, and its own filename is a hash
    rather than a post ID, so anything annotating posts has to go through this.

    Module-level rather than a method, because processors that merely *read* a
    media embedding - and so never subclass `EmbedMedia` - need it too.

    :param Path archive_path:  Archive to read the metadata from
    :param callable log:  Optional logger for explaining a failed read
    :return dict:  `{filename without extension: [post ID, ...]}`
    """
    post_ids = {}
    if not archive_path or not zipfile.is_zipfile(archive_path):
        return post_ids

    try:
        with zipfile.ZipFile(archive_path) as archive:
            if ".metadata.json" not in archive.namelist():
                return post_ids

            metadata = json.loads(archive.read(".metadata.json"))
    except (zipfile.BadZipFile, json.JSONDecodeError, KeyError, OSError) as e:
        if log:
            log(f"Could not read .metadata.json, post IDs are unavailable: {e}")
        return post_ids

    for entry in metadata.values():
        if not isinstance(entry, dict):
            continue
        for file in entry.get("files", []):
            filename = file.get("filename") if isinstance(file, dict) else None
            if filename:
                post_ids[".".join(filename.split(".")[:-1])] = entry.get("post_ids", [])

    return post_ids


class EmbedMedia(BasicProcessor):
    """
    Send each media file to a multimodal embedding model and store the vector it
    returns, so the files can be compared, mapped and searched by content.
    """

    media_label = "media file"
    media_label_plural = "media files"
    model_requirement_note = "not only text"
    working_filename = "compressed"

    annotation_label = "media_embedding"
    annotation_batch_size = 100

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
        Media datasets, but only where an embedding model is available.

        :param module:  Dataset or processor to check against
        :param ConfigManager|None config:  Context-aware configuration reader
        :return bool:
        """
        if config is None or not cls.compatibility.is_compatible_with(module, config=config):
            return False

        return bool(get_model_library(config, task="embed"))

    @classmethod
    def get_media_options(cls, config=None) -> dict:
        """
        Options controlling how a file is made smaller before it is sent.

        Subclasses override this; the surrounding model and amount options are
        the same everywhere and are added by `get_options()`.

        :param ConfigManager|None config:  Configuration reader (context-aware)
        :return dict:  Options for this processor
        """
        return {}

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
            "model_info": {
                "type": UserInput.OPTION_INFO,
                "help": f"The model must accept **{cls.media_label}**, {cls.model_requirement_note}. 4CAT cannot tell "
                        f"which models do, so every embedding model is listed here; one that cannot read "
                        f"{cls.media_label} will return an error.",
            },
            "model": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Embedding model",
                "options": get_model_library(config, task="embed") if config else {},
                "default": "",
            },
            "instruction": {
                "type": UserInput.OPTION_TEXT,
                "help": "[optional] Prompt",
                "default": f"Represent the {cls.media_label}.",
                "tooltip": f"An instruction sent to the model as a system prompt with each {cls.media_label}. It is "
                           f"not embedded itself: instruction-aware models like Qwen3-VL-Embedding use it to steer "
                           f"what the embedding captures, so tailoring it to your research question can improve "
                           f"results. Leave empty to use the model's own default.",
            },
        }

        options.update(cls.get_media_options(config))

        options["amount"] = {
            "type": UserInput.OPTION_TEXT,
            "help": f"No. of {cls.media_label_plural}",
            "default": 100,
            "min": 0,
            "coerce_type": int,
            "tooltip": f"Use '0' for all {cls.media_label_plural}. Each {cls.media_label} is a separate request, so "
                       f"this is slow for large datasets.",
        }
        
        options["save_annotations"] = {
            "type": UserInput.OPTION_ANNOTATION,
            "label": cls.annotation_label,
            "tooltip": "Add embeddings scores as annotations to the parent dataset.",
            "default": False,
            "hide_in_explorer": True
        }

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

        return query

    def check_requirements(self) -> str | None:
        """
        Check anything this processor needs beyond a model, before starting.

        Runs once, before any file is read, so a missing dependency is reported
        immediately rather than after the first item fails. Subclasses that need
        an external tool override this and can store what they resolved on
        `self`.

        :return str|None:  An error message, or `None` when everything is present.
        """
        return None

    def skip_reason(self, media_path) -> str | None:
        """
        Decide whether to leave a file out, before any work is done on it.

        :param Path media_path:  File that would be embedded
        :return str|None:  Why the file is skipped, or `None` to embed it.
        """
        return None

    @abc.abstractmethod
    def prepare_media(self, media_path, output_path) -> tuple:
        """
        Make one file smaller and return it as a base64 media descriptor.

        The file travels inside the request body, so the point is to send as few
        bytes as possible without losing what the model looks at.

        :param Path media_path:  File to prepare
        :param Path output_path:  Where to write the smaller version
        :return tuple:  `(media descriptor, original size, sent size)`
        """
        pass

    def resolve_model(self):
        """
        Resolve the chosen model to a server and a client for it.

        :return tuple|None:  `(model metadata, client)`, or `None` when
          something is missing - in which case the dataset has been finished
          with an error explaining what.
        """
        model_id = self.parameters.get("model")
        available_models = {
            k: v for k, v in self.config.get("llm.available_models", {}).items()
            if k in self.config.get("llm.enabled_models", [])
        }

        if model_id not in available_models:
            self.dataset.finish_with_error(f"Embedding model '{model_id}' is no longer available. Ask an admin to "
                                           f"enable it, or pick another model.")
            return None

        model = available_models[model_id]
        server = self.config.get("llm.servers", {}).get(model["server"])
        if not server:
            self.dataset.finish_with_error(f"The LLM server for model '{model_id}' is no longer configured.")
            return None

        try:
            client = LLMServerClient.get_client(self.config, server, self.log)
        except ValueError as e:
            self.dataset.finish_with_error(str(e))
            return None

        return model, client

    @staticmethod
    def encode(path) -> str:
        """
        Read a file and base64-encode it for transport in a request body.

        :param Path path:  File to encode
        :return str:  Base64-encoded contents
        """
        with path.open("rb") as infile:
            return base64.b64encode(infile.read()).decode("utf-8")

    def load_post_id_map(self) -> dict:
        """
        Map each media filename to the posts it was downloaded for.

        Read straight from the source archive rather than the staging area: the
        staging area is filled lazily as items are iterated, so the metadata is
        not reliably there before the first file is handled - and annotations
        are written as we go.

        :return dict:  `{filename without extension: [post ID, ...]}`
        """
        post_ids = read_post_id_map(self.source_file, log=self.dataset.log)
        self.dataset.log(f"Found post IDs for {len(post_ids):,} {self.media_label_plural} in .metadata.json")
        return post_ids

    def process(self):
        """
        Compress each file, embed it, and write one vector per file.
        """
        resolved = self.resolve_model()
        if not resolved:
            return

        model, client = resolved

        requirement_error = self.check_requirements()
        if requirement_error:
            self.dataset.finish_with_error(requirement_error)
            return

        instruction = self.parameters.get("instruction", "").strip()

        limit = self.parameters.get("amount", 100)
        max_processed = min(limit, self.source_dataset.num_rows) if limit else self.source_dataset.num_rows

        staging_area = self.dataset.get_staging_area()
        output_path = staging_area.joinpath(self.working_filename)

        save_annotations = self.parameters.get("save_annotations", False)
        # always, not only for annotations: the posts behind each file are what
        # later steps (clustering annotations, plotting by a post's date) need
        post_id_map = self.load_post_id_map()
        annotations = []

        embedded = 0
        failed_embeddings = 0
        max_failed_embeddings = 10
        skipped = 0
        processed = 0
        total_sent = 0

        embedding_error = ""

        self.dataset.update_status(f"Embedding {self.media_label_plural} with {model['local_id']}")

        with self.dataset.get_results_path().open("w", encoding="utf-8") as outfile:
            for item in self.source_dataset.iterate_items(self, staging_area=staging_area,
                                                          immediately_delete=False):
                if self.interrupted:
                    raise ProcessorInterruptedException(f"Interrupted while embedding {self.media_label_plural}")

                if processed >= max_processed:
                    break

                media_path = item.file if hasattr(item, "file") else None
                if not media_path or media_path.name == ".metadata.json":
                    # the archive carries its metadata alongside the media files
                    continue

                reason = self.skip_reason(media_path)
                if reason:
                    self.dataset.log(f"Skipping {media_path.name}: {reason}")
                    skipped += 1
                    continue

                processed += 1
                self.dataset.update_status(f"Embedding {self.media_label} {processed:,}/{max_processed:,} "
                                           f"({media_path.name})")

                try:
                    payload, original_size, sent_size = self.prepare_media(media_path, output_path)
                except ProcessorInterruptedException:
                    raise
                except Exception as e:
                    self.dataset.log(f"Skipping {media_path.name}: could not compress ({e})")
                    skipped += 1
                    continue

                if not payload:
                    self.dataset.log(f"Skipping {media_path.name}: compression produced no output")
                    skipped += 1
                    continue

                # do the actual embedding
                max_retries = 3
                retries = 0
                vector = None
                while retries < max_retries:
                    try:
                        vector = client.embed(model["local_id"], [instruction], media=[payload],
                                              text_as_instruction=True)[0]
                        break  # success!
                    except LLMServerException as e:
                        retries += 1
                        self.dataset.log(f"Error embedding {media_path.name}: {e}. Retrying ({retries}/{max_retries})...")
                        if retries >= max_retries:
                            embedding_error = f"Failed to embed {media_path.name} after {max_retries} attempts: {e}"
                            failed_embeddings += 1
                            break  # not a success...
                        time.sleep(2)  # wait a bit before retrying

                if vector:
                    # the filename is a hash, so carry the posts it came from into
                    # the result: makes it easier for child processors to reach .metadata.json
                    post_ids = post_id_map.get(media_path.stem, [])

                    time_created = int(time.time())
                    outfile.write(json.dumps({
                        "id": media_path.stem,
                        "text": media_path.name,
                        "filename": media_path.name,
                        "post_ids": post_ids,
                        "embedding": vector,
                        "dimensions": len(vector),
                        "model": model["local_id"],
                        "original_bytes": original_size,
                        "sent_bytes": sent_size,
                        "time_created": datetime.fromtimestamp(time_created).strftime("%Y-%m-%d %H:%M:%S"),
                        "time_created_utc": time_created,
                    }) + "\n")

                    if save_annotations:
                        # one vector can belong to several posts, and each gets its
                        # own annotation
                        for post_id in post_ids:
                            annotations.append({
                                "item_id": post_id,
                                "label": self.annotation_label,
                                "value": " ".join([str(value) for value in vector]),
                                "type": "text",
                            })

                    embedded += 1
                    total_sent += sent_size

                if embedded % self.annotation_batch_size == 0:
                    outfile.flush()
                    if annotations:
                        self.save_annotations(annotations, hide_in_explorer=True)
                        annotations = []

                if failed_embeddings >= max_failed_embeddings:
                    self.save_annotations(annotations, hide_in_explorer=True)
                    self.dataset.finish_with_error(f"Too many failed embeddings ({failed_embeddings}); {embedding_error}")
                    return

                self.dataset.update_progress(processed / max_processed)

        if annotations:
            self.save_annotations(annotations, hide_in_explorer=True)

        if not embedded:
            self.dataset.finish_with_error(f"No {self.media_label_plural} could be embedded.")
            return

        if save_annotations and not post_id_map:
            self.dataset.log("No annotations were written: the archive has no .metadata.json linking files to posts.")

        status = f"Embedded {embedded:,} {self.media_label_plural} ({total_sent / 1024 / 1024:.1f} MB sent in total)"
        if skipped:
            status += f", skipped {skipped:,}"

        if failed_embeddings:
            self.dataset.finish_with_warning(
                embedded, f"{status}. {failed_embeddings:,} {self.media_label_plural} could not be embedded; see "
                          f"the log for details.")
            return

        self.dataset.update_status(status, is_final=True)
        self.dataset.finish(embedded)

    @staticmethod
    def map_item(item):
        """
        Map a media embedding to a flat row.

        Deliberately the same shape `text-embeddings` produces, so that the
        processors chaining off embeddings work on these unchanged.

        :param item:  Item to map
        :return MappedItem:  Mapped item
        """
        embedding = item.get("embedding", [])

        return MappedItem({
            "id": item.get("id"),
            "text": item.get("text"),
            "filename": item.get("filename"),
            "post_ids": ", ".join([str(post_id) for post_id in item.get("post_ids", [])]),
            "model": item.get("model"),
            "dimensions": item.get("dimensions"),
            "embedding": " ".join([str(value) for value in embedding]),
            "original_bytes": item.get("original_bytes"),
            "sent_bytes": item.get("sent_bytes"),
            "timestamp": item.get("time_created"),
        })
