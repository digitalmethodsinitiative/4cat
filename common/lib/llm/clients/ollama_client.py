"""
Centralized HTTP client for communicating with an Ollama server.

This class owns all direct HTTP calls to Ollama's REST API and provides shared static
helpers for capability parsing, display-name formatting, and building canonical
llm.available_models entries. It is a plain helper with no 4CAT base-class dependency.
"""
import requests

from common.lib.llm.llm_client import LLMProviderClient


class OllamaClient(LLMProviderClient):
    type = "ollama"

    _models_info_path = "/api/tags"
    _models_info_key = "models"
    _model_id_key = "model"

    def list_models(self) -> list[dict]:
        """
        List all models available.

        For Ollama, get some additional model info via an extra API request.

        :return list[dict]: List of models available.:
        """
        models = super().list_models()
        result = []
        for model in models:
            try:
                model_info = self._session.post(
                    f"{self.base_url}/api/show",
                    json={"model": model[self._model_id_key]},
                    headers=self._headers,
                    timeout=self.timeout,
                ).json()
                result.append({**model, "model_info": model_info["model_info"]})
            except (requests.exceptions.HTTPError, KeyError) as e:
                self.log.warning(
                    f"{self.__class__.__name__}: failed to fetch additional model info for model {model[self._model_id_key]}: {e}")

        return result



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
        if meta is None:
            return []

        capabilities = meta.get("capabilities", [])
        media_types: list[str] = []

        _cap_map = {
            "completion": "text",
            "vision": "image",
            "embedding": "embedding",
        }
        for cap in capabilities:
            mapped = _cap_map.get(cap)
            if mapped and mapped not in media_types:
                media_types.append(mapped)

        # Fallback: GGUF-level vision signals when capabilities list gives no image info
        if "image" not in media_types:
            details = meta.get("details", {})
            model_info = meta.get("model_info", {})
            projector_info = meta.get("projector_info")

            has_clip_family = "clip" in (details.get("families") or [])
            has_vision_keys = any(k.startswith("vision.") for k in model_info)
            has_projector = bool(projector_info)

            if has_clip_family or has_vision_keys or has_projector:
                media_types.append("image")

        return media_types

    def format_display_name(self, meta: dict) -> str:
        """
        Build a human-readable display name for a model.

        :param model_id:    Raw Ollama model identifier (e.g. ``"llama3:8b"``).
        :param meta:        ``/api/show`` response dict, or ``None``.
        :returns:           Human-readable display name string.
        """
        model_name = self.get_model_id(meta)

        extra_bits = []
        if meta.get("model_info"):
            if meta["model_info"].get("general.basename"):
                model_name = meta["model_info"]["general.basename"]

            if meta["model_info"].get("general.finetune"):
                extra_bits.append(meta["model_info"]["general.finetune"])

            if meta["model_info"].get("general.size_label"):
                extra_bits.append(meta["model_info"]["general.size_label"])

        elif meta.get("details") and meta["details"].get("parameter_size"):
            extra_bits.append(f"{meta['details']['parameter_size']} parameters")

        model_name += f" ({', '.join(extra_bits)})"

        return model_name

    def get_model_card_url(self, meta: dict) -> str:
        """
        Get a URL for a model card for a given model

        :param meta:  Model metadata
        :return str:  Model card URL (empty string if unavailable)
        """
        return f"https://ollama.com/library/{meta['model']}"

    def pull_model(self, model_id: str, stream: bool = False) -> bool:
        """Pull a model from the Ollama registry.

        :param model_id:    Model name (e.g. ``"llama3:8b"``).
        :param stream:      Whether to stream the response (default ``False``).
        :returns:           ``True`` on success, ``False`` on failure.
        """
        try:
            r = self._session.post(
                f"{self.base_url}/api/pull",
                headers=self._headers,
                json={"model": model_id, "stream": stream},
                timeout=600,
            )

            if r.status_code != 200 and self.log:
                self.log.warning(
                    f"{self.__class__.__name__}: failed to pull model {model_id} from {self.base_url}, status code {r.status_code}: {r.text}")

            return r.status_code == 200

        except requests.RequestException as e:
            if self.log:
                self.log.warning(
                    f"{self.__class__.__name__}: failed to pull model {model_id} from {self.base_url}: {e}")

            return False

    def delete_model(self, model_id: str) -> bool:
        """Delete a model from the Ollama server.

        :param model_id:    Model name (e.g. ``"llama3:8b"``).
        :returns:           ``True`` on success, ``False`` on failure.
        """
        try:
            r = self._session.delete(
                f"{self.base_url}/api/delete",
                headers=self._headers,
                json={"model": model_id},
                timeout=30,
            )
            if r.status_code != 200 and self.log:
                self.log.warning(
                    f"{self.__class__.__name__}: failed to delete model {model_id} from {self.base_url}, status code {r.status_code}: {r.text}")
            return r.status_code == 200
        except requests.RequestException as e:
            if self.log:
                self.log.warning(
                    f"{self.__class__.__name__}: failed to delete model {model_id} from {self.base_url}: {e}")
            return False
