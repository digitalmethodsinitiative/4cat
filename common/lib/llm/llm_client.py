"""
Centralized HTTP client for communicating with an LLM server.

This class owns all direct HTTP calls to the server's REST API and provides
shared static helpers for capability parsing, display-name formatting, and
building canonical llm.available_models entries. It is a plain helper with no
4CAT base-class dependency.
"""

from abc import abstractmethod

import requests
import re

from common.lib.exceptions import LLMServerException

class LLMServerClient:
    _headers = {}
    server_config = {}

    @staticmethod
    def get_client(config, server_config: dict, log) -> "LLMServerClient":
        """
        Get a client for an LLM server

        Returns the appropriate sub-class depending on the server type.

        :param config:  4CAT config reader
        :param dict server_config:  Server parameters, as configured in
          4CAT
        :return LLMServerClient:  A client object appropriate for the server.
        """
        # in-line import because we otherwise get circular import shenanigans
        from common.lib.llm.clients.ollama_client import OllamaClient
        from common.lib.llm.clients.litellm_client import LiteLLMClient
        from common.lib.llm.clients.openai_client import OpenAICompatibleClient
        from common.lib.llm.clients.thirdparty_client import ThirdPartyClient

        for client_type in (OllamaClient, LiteLLMClient, OpenAICompatibleClient, ThirdPartyClient):
            if client_type.type == server_config["type"]:
                return client_type(config, server_config, log=log)

        raise ValueError(f"LLMServerClient: Unknown server type {server_config['type']}")

    def __init__(self, config, server_config: dict, timeout: int = 10, log=None) -> None:
        """
        HTTP client for an LLM Server

        :param config:  4CAT config reader
        :param dict server_config:  Server parameters, as configured in 4CAT
        :param int timeout: Default request timeout in seconds.
        :param Logger log:  4CAT log handler
        """
        self.config = config
        self.server_config = server_config

        self.timeout = timeout
        self.auth_type = server_config.get("auth_header")
        self.auth_key = server_config.get("auth_key")
        self.timeout = timeout

        self.base_url = server_config["url"].rstrip("/")
        if self.base_url.endswith("v1"):
            # get rid of the 'v1' - we'll add this in the path.
            self.base_url = self.base_url[:-2].rstrip("/")

        self._session = requests.Session()
        self._headers = {"Content-Type": "application/json"}

        if self.auth_type:
            # The setting asks for a header *name*, but "Authorization: Bearer"
            # is the natural thing to type and is what people paste from curl
            # examples. As a header name that is malformed - requests raises
            # InvalidHeader, which surfaces as "server unavailable" and sends
            # people hunting for a network problem. So accept both spellings:
            # anything after a colon is treated as a prefix on the value.
            header_name, _, value_prefix = self.auth_type.partition(":")
            header_name = header_name.strip()
            value_prefix = value_prefix.strip()

            auth_value = self.auth_key or ""
            if value_prefix and not auth_value.lower().startswith(value_prefix.lower()):
                auth_value = f"{value_prefix} {auth_value}".strip()

            if header_name:
                self._headers[header_name] = auth_value

        self.log = log

    def get_status(self) -> bool | int:
        """
        Check if the server is reachable and responding to requests

        :return:  `False` if the server is not responding, or an HTTP status code.
        """
        try:
            r = self._session.get(
                f"{self.base_url}{self._models_info_path}",
                headers=self._headers,
                timeout=self.timeout,
            )
            if self.log and r.status_code != 200:
                self.log.warning(
                    f"{self.__class__.__name__}: server responded with status code {r.status_code} during availability check: {r.text}")
            return r.status_code
        except requests.RequestException as e:
            if self.log:
                self.log.warning(f"{self.__class__.__name__}: server is not available at {self.base_url}: {e}")
            return False

    def list_models(self) -> list[dict]:
        """
        List available models from the LLM server.

        :returns:   List of model dicts (un-mapped), or `[]` on failure.
        """
        try:
            r = self._session.get(
                f"{self.base_url}{self._models_info_path}",
                headers=self._headers,
                timeout=self.timeout,
            )
            if r.status_code == 200:
                return r.json().get(self._models_info_key, [])
            if self.log:
                self.log.warning(
                    f"{self.__class__.__name__}: failed to list models from {self.base_url}, status code {r.status_code}: {r.text}")
        except requests.RequestException as e:
            if self.log:
                self.log.warning(f"{self.__class__.__name__}: failed to list models from {self.base_url}: {e}")
        return []

    def build_model_entry(self, meta: dict) -> dict:
        """
        Build a canonical `llm.available_models` entry for a model.

        :param meta:  `/api/show` response dict, or `None` if unavailable.
        :returns:  Dict ready to store under `llm.available_models[model_id]`.
        """
        return {
            "id": self.get_global_model_id(meta),
            "local_id": self.get_model_id(meta),
            "name": self.format_display_name(meta),
            "model_card": self.get_model_card_url(meta),
            "server": self.server_config["_id"],
            "wrapper": self.server_config["type"],
            "supported_media_types": self.parse_supported_media_types(meta),
            "supported_tasks": self.parse_supported_tasks(meta),
            "metadata": meta,
        }

    def parse_supported_tasks(self, meta: dict) -> list[str]:
        """
        Derive the tasks a model can be used for from its metadata.

        Most servers do not report this. An OpenAI-compatible `/v1/models` lists
        an id and nothing else, so there is no capability field to read. The
        fallback is therefore the model's own name: an id containing "embed"
        (Qwen3-VL-Embedding, mxbai-embed-large, nomic-embed-text) reads as an
        embedder, anything else as generative.

        # todo: check if there's a more rigid way of separating later.

        :param dict meta:  Model metadata, or `None` if unavailable.
        :returns list[str]:  Supported tasks - `"generate"`, `"embed"`, or both.
        """
        try:
            model_id = str(self.get_model_id(meta) or "")
        except (KeyError, TypeError):
            # nothing to go on; assume generative, which is how every server
            # behaved before embedding support existed
            return ["generate"]

        return ["embed"] if "embed" in model_id.lower() else ["generate"]

    def embed(self, model_id: str, inputs: list, media: list | None = None, timeout: int = 300,
              text_as_instruction: bool = False) -> list[list[float]]:
        """
        Embed one or more inputs, returning one vector per input.

        Deliberately *not* routed through `LLMAdapter`/LangChain. LangChain's
        embedding interface is text-only, so it
        cannot handle multimodal embeddings.

        A client that cannot embed media must raise an exception when `media` is given
        rather than embedding the text alone.

        :param str model_id:  Model ID *within this server's context* (i.e. a
          `local_id`, not a global model ID).
        :param list inputs:  Inputs to embed.
        :param list media:  Optional media to embed, one entry per input and
          paired by index, for servers that support multimodal embedding. Each
          entry is a descriptor dict:

              {"type": "video"|"image", "mime": "video/mp4", "data": "<base64>"}

          or, in place of `data`, a `"url"` the server can fetch itself. Each
          client translates this to whatever its own API expects.
        :param int timeout:  Request timeout in seconds.
        :param bool text_as_instruction:  With media, treat `inputs[i]` as an
          instruction that steers the embedding rather than as text to embed
          along with the media. Clients without such a distinction ignore it.
        :returns list[list[float]]:  One vector per input, in input order.
        """
        raise LLMServerException(
            f"Embedding is not supported for {self.server_config.get('type', 'this')} connections, so the model "
            f"'{model_id}' cannot be used to generate embeddings. Use a model on an Ollama or OpenAI-compatible "
            f"connection instead.")

    def get_model_card_url(self, meta: dict) -> str:
        """
        Get a URL for a model card for a given model

        :param dict meta:  Model metadata
        :return str:  Model card URL (empty string if unavailable)
        """
        return ""

    @abstractmethod
    def parse_supported_media_types(self, meta: dict) -> list[str]:
        """
        Derive the media types a model supports from its Ollama metadata.

        **Primary path**: reads `meta["capabilities"]`:
        - `"completion"` → `"text"`
        - `"vision"`     → `"image"`
        - `"embedding"`  → `"embedding"`

        **Fallback path** (used when capabilities are absent or only yield `"text"`):
        inspects GGUF `model_info` / `details` for vision signals and adds
        `"image"` if any are found.

        :param meta:    `/api/show` response dict, or `None`.
        :returns:       Ordered list of supported media type strings.
                        Returns `[]` when `meta` is `None` (unknown — callers
                        should include the model, not block it).
        """
        pass

    @abstractmethod
    def format_display_name(self, meta: dict) -> str:
        """
        Build a human-readable display name for a model.

        :param dict meta:  Model metadata
        :returns str:  Human-readable display name string.
        """
        pass

    def get_model_id(self, meta: dict) -> str:
        """
        Choose a model identifier based on model metadata.

        This is the ID within the server context, i.e. it is not guaranteed
        to be globally unique (use `get_global_model_id()` instead).

        :param dict meta:  Model metadata
        :return str:  Model ID
        """
        return meta[self._model_id_key]

    def get_global_model_id(self, meta: dict) -> str:
        """
        Choose a model identifier based on model metadata.

        This needs to be a *globally* unique ID, i.e. if multiple servers
        provide the same model, the ID should still be unique per server.

        :param dict meta:  Model metadata
        :return str:  Model ID
        """
        domain = re.sub(r"^https?://", "", self.server_config["url"])
        domain = domain.rstrip("/")
        return f"{self.server_config['type']}://{domain}/{self.get_model_id(meta)}"


def supports_task(model: dict, task: str = "generate") -> bool:
    """
    Check whether a model entry can be used for a given task.

    :param dict model:  A single `llm.available_models` entry.
    :param str task:  Task to check for - `"generate"` or `"embed"`.
    :return bool:  Whether the model supports the task.
    """
    return task in model.get("supported_tasks", ["generate"])


def get_model_library(config, task: str = "generate") -> dict:
    """
    Get the LLM models available for a given task, grouped by server.

    :param config:  4CAT config reader (context-aware, so per-user `llm.access`
      is respected)
    :param str task:  Task the model must support - `"generate"` or `"embed"`.
    :return dict:  `{server name: {model ID: model display name}}`, shaped for
      a `UserInput.OPTION_CHOICE` option.
    """
    available_models = config.get("llm.available_models", {})
    enabled_model_ids = config.get("llm.enabled_models", [])
    servers = config.get("llm.servers", {})
    if not config.get("llm.access"):
        enabled_model_ids = [_ for _ in enabled_model_ids if _.startswith("thirdparty")]

    models_option = {}
    for key, value in {k: v for k, v in available_models.items() if k in enabled_model_ids}.items():
        if not supports_task(value, task):
            continue

        server = servers[value["server"]]
        if server["name"] not in models_option:
            models_option[server["name"]] = {}

        models_option[server["name"]][key] = value["name"]

    return models_option
