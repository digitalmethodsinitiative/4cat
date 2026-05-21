"""
Centralized HTTP client for communicating with an OpenAI compatible server.

This class owns all direct HTTP calls to an OpenAI style REST API and provides shared
static helpers for capability parsing, display-name formatting, and building
canonical llm.available_models entries. It is a plain helper with no 4CAT
base-class dependency.
"""
from common.lib.llm.llm_client import LLMProviderClient


class LMStudioClient(LLMProviderClient):
    type = "openai-like"

    _models_info_path = "/api/v1/models"
    _models_info_key = "models"
    _model_id_key = "key"

    def parse_supported_media_types(self, meta: dict) -> list[str]:
        """
        Derive the media types a model supports from its LiteLLM metadata.

        :param meta:    ``model info`` response dict, or ``None``.
        :returns:       Ordered list of supported media type strings.
                        Returns ``[]`` when ``meta`` is ``None``
        """
        media_types = {"text"}  # far as I can tell, text is always supported

        if meta is None or not meta.get("capabilities"):
            return list(media_types)

        if meta["capabilities"].get("vision"):
            media_types.add("image")

        # no way to tell if model supports embeddings input as far as I can see...

        return list(media_types)

    def format_display_name(self, meta: dict) -> str:
        """
        Build a human-readable display name for a model.

        :param model_id:    Raw Ollama model identifier (e.g. ``"llama3:8b"``).
        :param meta:        ``/api/show`` response dict, or ``None``.
        :returns:           Human-readable display name string.
        """
        model_name = self.get_model_id(meta)

        if meta.get("display_name"):
            model_name = meta["display_name"]

        extra_bits = []
        if meta.get("publisher"):
            extra_bits.append(meta["publisher"])

        if meta.get("params_string"):
            extra_bits.append(meta["params_string"])

        model_name += f" ({', '.join(extra_bits)})"

        return model_name
