"""
Centralized HTTP client for communicating with an OpenAI compatible server.

This includes vLLM and LM Studio. And LiteLLM, technically, but LiteLLM has
some useful API endpoints exclusive to it that we can benefit from, so use
the dedicated class for tht instead.
"""
import requests
from common.lib.llm.llm_client import LLMServerClient


class OpenAICompatibleClient(LLMServerClient):
    type = "openai-like"

    _models_info_path = "/api/v1/models"
    _models_info_key = "models"
    _model_id_key = "key"

    def get_status(self) -> bool | int:
        """
        Check if the server is reachable
        Tries the LM studio native endpoint first then falls back to
        standard OpenAI-spec /v1/models endpoint.
        """
        
        # LM Studio native path
        try:
            r = self._session.get(
                f"{self.base_url}{self._models_info_path}",
                headers=self._headers,
                timeout=self.timeout,
            )
            if r.status_code == 200:
                return 200
        except requests.RequestException:
            pass

        # Standard OpenAI-compatible fallback
        try:
            r = self._session.get(
                f"{self.base_url}/v1/models",
                headers=self._headers,
                timeout=self.timeout,
            )
            if r.status_code == 200:
                return 200
            if self.log:
                self.log.warning(
                    f"{self.__class__.__name__}: server responded with status code {r.status_code} during availability check: {r.text}")
            return r.status_code
        except requests.RequestException as e:
            if self.log:
                self.log.warning(f"{self.__class__.__name__}: server is not available at {self.base_url}: {e}")
            return False
            
    def list_models(self) -> list[dict]:
        """
        List available models from server.
        
        Same try logic as get_status
        """
        
                # LM Studio native path
        try:
            r = self._session.get(
                f"{self.base_url}{self._models_info_path}",
                headers=self._headers,
                timeout=self.timeout,
            )
            if r.status_code == 200:
                return r.json().get(self._models_info_key, [])
        except requests.RequestException:
            pass

        # Standard OpenAI-compatible fallback
        try:
            r = self._session.get(
                f"{self.base_url}/v1/models",
                headers=self._headers,
                timeout=self.timeout,
            )
            if r.status_code == 200:
                return r.json().get("data", [])
            if self.log:
                self.log.warning(
                    f"{self.__class__.__name__}: failed to list models from {self.base_url}, status code {r.status_code}: {r.text}")
        except requests.RequestException as e:
            if self.log:
                self.log.warning(f"{self.__class__.__name__}: failed to list models from {self.base_url}: {e}")
        return []
        
    def get_model_id(self, meta: dict) -> str:
        """
        Choose model based on metadata. Supports LM Studio's `key` field and OpenAI spec `id` field
        """
        
        return meta.get(self._model_id_key) or meta.get("id", "")

    def parse_supported_media_types(self, meta: dict) -> list[str]:
        """
        Derive the media types a model supports from its LiteLLM metadata.

        :param dict meta:  `model info` response dict, or `None`.
        :returns list[str]:  Ordered list of supported media type strings.
          Returns `[]` when `meta` is `None`
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
=
        :param dict meta:  `/api/show` response dict, or `None`.
        :returns str:  Human-readable display name string.
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
