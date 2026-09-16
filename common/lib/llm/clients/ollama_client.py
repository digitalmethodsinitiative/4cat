"""
Centralized HTTP client for communicating with an Ollama server.
"""
import requests

from common.lib.exceptions import LLMServerException
from common.lib.llm.llm_client import LLMServerClient


class OllamaClient(LLMServerClient):
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
                result.append({**model, "metadata": model_info})
            except (requests.exceptions.HTTPError, KeyError) as e:
                self.log.warning(
                    f"{self.__class__.__name__}: failed to fetch additional model info for model {model[self._model_id_key]}: {e}")

        return result



    def parse_supported_media_types(self, meta: dict) -> list[str]:
        """Derive the media types a model supports from its Ollama metadata.

        **Primary path**: reads `meta["capabilities"]`:
        - `"completion"` → `"text"`
        - `"vision"`     → `"image"`
        - `"embedding"`  → `"text"` (an embedder still consumes text)

        **Fallback path** (used when capabilities are absent or only yield `"text"`):
        inspects GGUF `model_info` / `details` for vision signals and adds
        `"image"` if any are found.

        :param dict meta:  `/api/show` response dict, or `None`.
        :returns list[str]:  Ordered list of supported media type strings.
          Returns `[]` when `meta` is `None` (unknown — callers should
          include the model, not block it).
        """
        if meta is None or not (meta.get("metadata") or meta.get("capabilities")):
            return []

        capabilities = self._get_capabilities(meta)
        media_types: list[str] = []

        _cap_map = {
            "completion": "text",
            "embedding": "text",
            "vision": "image",
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

    @staticmethod
    def _get_capabilities(meta: dict) -> list[str]:
        """
        Read a model's capability list.

        Ollama reports capabilities in two places: nested under `metadata` for
        the `/api/show` response `list_models()` attaches, and inline on the
        `/api/tags` entry itself. Prefer the former and fall back to the latter,
        so a model whose `/api/show` request failed is still classified.

        :param dict meta:  Model metadata, or `None`.
        :returns list[str]:  Ollama capability strings, or `[]` if unknown.
        """
        if not meta:
            return []

        metadata = meta.get("metadata") or {}
        return metadata.get("capabilities") or meta.get("capabilities") or []

    def parse_supported_tasks(self, meta: dict) -> list[str]:
        """
        Derive the tasks a model supports from its Ollama capabilities.

        :param dict meta:  `/api/show` response dict, or `None`.
        :returns list[str]:  Supported tasks - `"generate"`, `"embed"`, or both.
        """
        capabilities = self._get_capabilities(meta)

        tasks = []
        if "completion" in capabilities:
            tasks.append("generate")
        if "embedding" in capabilities:
            tasks.append("embed")

        # An unreachable or partial /api/show leaves nothing to go on. Assume
        # generation, matching the base class, rather than hiding the model
        # from every processor at once.
        return tasks if tasks else ["generate"]

    def embed(self, model_id: str, inputs: list, media: list | None = None, timeout: int = 300) -> list[list[float]]:
        """
        Embed inputs via Ollama's `/api/embed` endpoint.

        The endpoint accepts a list and returns one vector per item, so a caller
        that batches its inputs gets one round-trip per batch rather than per
        item.

        Text only. `/api/embed` takes `model`, `input`, `truncate`, `options`,
        `keep_alive` and `dimensions` - there is no image parameter, and Ollama
        *silently discards* an `images` field rather than rejecting it, handing
        back a text-only vector that looks entirely valid (verified against
        Ollama 0.34.1; see ollama/ollama#5304 and #7677, both still open). So
        refuse media here explicitly: a quiet wrong answer is worse than a loud
        failure, and this is the only place that can tell the difference.

        :param str model_id:  Ollama model name, e.g. `"mxbai-embed-large:latest"`.
        :param list inputs:  Strings to embed.
        :param list media:  Not supported; passing any raises.
        :param int timeout:  Request timeout in seconds.
        :returns list[list[float]]:  One vector per input, in input order.
        :raises LLMServerException:  If media is passed, if the server errors,
          or if it returns a number of vectors that does not match the number of
          inputs (which would silently misalign vectors with their items).
        """
        if media:
            raise LLMServerException(
                "Ollama cannot produce multimodal embeddings: its /api/embed endpoint has no image parameter and "
                "ignores one without reporting an error, which would yield text-only vectors that look valid. Use a "
                "server that supports multimodal embedding instead.")

        if not inputs:
            return []

        try:
            response = self._session.post(
                f"{self.base_url}/api/embed",
                headers=self._headers,
                json={"model": model_id, "input": inputs},
                timeout=timeout,
            )
        except requests.RequestException as e:
            raise LLMServerException(f"Could not reach Ollama server at {self.base_url}: {e}")

        if response.status_code != 200:
            raise LLMServerException(
                f"Ollama server returned status {response.status_code} while embedding with model "
                f"'{model_id}': {response.text}")

        try:
            embeddings = response.json().get("embeddings")
        except ValueError as e:
            raise LLMServerException(f"Ollama server returned invalid JSON while embedding: {e}")

        if not embeddings:
            raise LLMServerException(f"Ollama server returned no embeddings for model '{model_id}'")

        if len(embeddings) != len(inputs):
            raise LLMServerException(
                f"Ollama server returned {len(embeddings)} embeddings for {len(inputs)} inputs; cannot map "
                f"vectors back to items")

        return embeddings

    def format_display_name(self, meta: dict) -> str:
        """
        Build a human-readable display name for a model.

        :param dict meta:  `/api/show` response dict, or `None`.
        :returns str:  Human-readable display name string.
        """
        model_name = self.get_model_id(meta)

        extra_bits = []
        if meta.get("metadata") and meta["metadata"].get("model_info"):
            more_meta = meta["metadata"]["model_info"]
            if more_meta.get("general.basename"):
                model_name = more_meta["general.basename"]

            if more_meta.get("general.finetune"):
                extra_bits.append(more_meta["general.finetune"])

            if more_meta.get("general.size_label"):
                extra_bits.append(more_meta["general.size_label"])

        elif meta.get("details") and meta["details"].get("parameter_size"):
            extra_bits.append(f"{meta['details']['parameter_size']} parameters")

        if extra_bits:
            model_name += f" ({', '.join(extra_bits)})"

        return model_name

    def get_model_card_url(self, meta: dict) -> str:
        """
        Get a URL for a model card for a given model

        :param dict meta:  Model metadata
        :return str:  Model card URL (empty string if unavailable)
        """
        return f"https://ollama.com/library/{meta['model']}"

    def pull_model(self, model_id: str, stream: bool = False) -> bool:
        """
        Pull a model from the Ollama registry.

        :param dict model_id:  Model name (e.g. `"llama3:8b"`).
        :param str stream:  Whether to stream the response (default `False`).
        :returns bool:  `True` on success, `False` on failure.
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
        """
        Delete a model from the Ollama server.

        :param str model_id:  Model name (e.g. `"llama3:8b"`).
        :returns bool:  `True` on success, `False` on failure.
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
