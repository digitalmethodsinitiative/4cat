"""
Centralized HTTP client for communicating with an LLM provider.

This class owns all direct HTTP calls to the provider's REST API and provides
shared static helpers for capability parsing, display-name formatting, and
building canonical llm.available_models entries. It is a plain helper with no
4CAT base-class dependency.
"""

from abc import abstractmethod

import requests


class LLMProviderClient:
    _headers = {}
    _meta = {}

    @staticmethod
    def get_client(config, provider_config: dict) -> "LLMProviderClient":
        """
        Get a client for an LLM provider

        Returns the appropriate sub-class depending on the provider type.

        :param config:  4CAT config reader
        :param dict provider_config:  Provider parameters, as configured in
          4CAT
        :return LLMProviderClient:
        """
        # in-line import because we otherwise get circular import shenanigans
        from common.lib.llm.ollama_client import OllamaClient
        from common.lib.llm.litellm_client import LiteLLMClient
        from common.lib.llm.lmstudio_client import LMStudioClient
        from common.lib.llm.thirdparty_client import ThirdPartyClient

        for client_type in (OllamaClient, LiteLLMClient, LMStudioClient, ThirdPartyClient):
            if client_type.type == provider_config["type"]:
                return client_type(config, provider_config)

        raise ValueError(f"LLMProviderClient: Unknown provider type {provider_config['type']}")

    def __init__(self, config, provider_config: dict, timeout: int = 10, log=None) -> None:
        """
        HTTP client for an LLM Provider

        :param dict provider_config:  Provider parameters, as configured in 4CAT
        :param int timeout: Default request timeout in seconds.
        :param Logger log:  4CAT log handler
        """
        self.config = config

        self._meta = provider_config
        self.base_url = provider_config["url"].rstrip("/")
        self.auth_type = provider_config.get("auth_header")
        self.auth_key = provider_config.get("auth_key")
        self.timeout = timeout

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
        """List available models from the Ollama server.

        :returns:   List of model dicts, or ``[]`` on failure.
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
        Build a canonical ``llm.available_models`` entry for a model.

        :param model_id:        Raw model identifier.
        :param display_name:    Human-readable name (from ``format_display_name``).
        :param meta:            ``/api/show`` response dict, or ``None`` if unavailable.
        :returns:               Dict ready to store under ``llm.available_models[model_id]``.
        """
        return {
            "id": self.get_global_model_id(meta),
            "local_id": self.get_model_id(meta),
            "name": self.format_display_name(meta),
            "model_card": self.get_model_card_url(meta),
            "provider_type": self._meta["type"],
            "provider": self._meta["url"],
            "supported_media_types": self.parse_supported_media_types(meta),
            "metadata": meta,
        }

    def get_model_card_url(self, meta: dict) -> str:
        """
        Get a URL for a model card for a given model

        :param meta:  Model metadata
        :return str:  Model card URL (empty string if unavailable)
        """
        return ""

    @abstractmethod
    def parse_supported_media_types(self, meta: dict) -> list[str]:
        """Derive the media types a model supports from its Ollama metadata.

        **Primary path**: reads ``meta["capabilities"]``:
        - ``"completion"`` → ``"text"``
        - ``"vision"``     → ``"image"``
        - ``"embedding"``  → ``"embedding"``

        **Fallback path** (used when capabilities are absent or only yield ``"text"``):
        inspects GGUF ``model_info`` / ``details`` for vision signals and adds
        ``"image"`` if any are found.

        :param meta:    ``/api/show`` response dict, or ``None``.
        :returns:       Ordered list of supported media type strings.
                        Returns ``[]`` when ``meta`` is ``None`` (unknown — callers
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

        This is the ID within the provider context, i.e. it is not guaranteed
        to be globally unique (use `get_global_model_id()` instead).

        :param dict meta:  Model metadata
        :return str:  Model ID
        """
        return meta[self._model_id_key]

    def get_global_model_id(self, meta: dict) -> str:
        """
        Choose a model identifier based on model metadata.

        This needs to be a *globally* unique ID, i.e. if multiple providers
        provide the same model, the ID should still be unique per provider.

        :param dict meta:  Model metadata
        :return str:  Model ID
        """
        return "-".join((self._meta["type"], self._meta["url"], self.get_model_id(meta)))