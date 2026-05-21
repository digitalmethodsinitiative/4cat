"""
Centralized HTTP client for communicating with a LiteLLM server.

This class owns all direct HTTP calls to LiteLLM's REST API and provides shared
static helpers for capability parsing, display-name formatting, and building
canonical llm.available_models entries. It is a plain helper with no 4CAT
base-class dependency.

This class is primarily intended for interfacing with LiteLLM, but since
LiteLLM itself is mostly OpenAI API-compatible, this can be used to interface
with the OpenAI API as well.
"""
import requests

from common.lib.llm.llm_client import LLMProviderClient

class LiteLLMClient(LLMProviderClient):
    type = "litellm"

    _models_info_path = "/model/info"
    _models_info_key = "data"
    _model_id_key = "model_name"

    def parse_supported_media_types(self, meta: dict) -> list[str]:
        """
        Derive the media types a model supports from its LiteLLM metadata.

        :param meta:    ``model info`` response dict, or ``None``.
        :returns:       Ordered list of supported media type strings.
                        Returns ``[]`` when ``meta`` is ``None``
        """
        if meta is None or not meta.get("model_info"):
            return []

        media_types = {"text"}  # far as I can tell, text is always supported
        if meta["model_info"].get("supports_vision"):
            media_types.add("image")

        if meta["model_info"].get("supports_audio_input"):
            media_types.add("sound")

        # no way to tell if model supports embeddings input as far as I can see...

        return list(media_types)

    def format_display_name(self, meta: dict) -> str:
        """
        Build a human-readable display name for a model.

        :param model_id:    Raw Ollama model identifier (e.g. ``"llama3:8b"``).
        :param meta:        ``/api/show`` response dict, or ``None``.
        :returns:           Human-readable display name string.
        """
        model_name = self.get_global_model_id(meta)

        if meta.get("model_name"):
            model_name = meta["model_name"]

        if meta["litellm_params"].get("model"):
            model_name = "/".join(meta["litellm_params"].get("model").split("/")[1:])

        return model_name