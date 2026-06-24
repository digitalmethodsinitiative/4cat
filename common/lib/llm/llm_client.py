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

class LLMServerClient:
    _headers = {}
    server_config = {}

    @staticmethod
    def get_client(config, server_config: dict) -> "LLMServerClient":
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
                return client_type(config, server_config)

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
            # get rid of the 'v1' - we'll add this in the path
            self.base_url = f"{self.base_url[:-2]}"

        self._session = requests.Session()
        self._headers = {"Content-Type": "application/json"}

        if self.auth_type:
            self._headers[self.auth_type] = self.auth_key

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
            "metadata": meta,
        }

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