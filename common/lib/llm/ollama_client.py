"""
Centralized HTTP client for communicating with an Ollama server.

This class owns all direct HTTP calls to Ollama's REST API and provides shared static
helpers for capability parsing, display-name formatting, and building canonical
llm.available_models entries. It is a plain helper with no 4CAT base-class dependency.
"""

import re
import requests

from common.lib.llm.llm_client import LLMProviderClient

class OllamaClient(LLMProviderClient):
    type = "ollama"

    _models_info_path = "/api/tags"
    _models_info_key = "models"
    _model_id_key = "model"

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

        :param dict meta:  Model metadata
        :returns str:  Human-readable display name string.
        """
        model_info = meta.get("model_info", {}) if meta else {}
        model_id = self.get_global_model_id(meta)
        details = meta.get("details", {}) if meta else {}

        basename = None
        for key in ("general.basename", "general.base_model.0.name"):
            val = model_info.get(key)
            if val:
                basename = str(val).strip()
                break
        if not basename:
            basename = model_id.split(":", 1)[0].replace("-", " ").replace("_", " ").strip() or model_id

        def _parse_param_count(val):
            if val is None:
                return None
            if isinstance(val, int):
                return val
            if isinstance(val, float):
                return int(val)
            s = str(val).strip().replace(",", "")
            if not s:
                return None
            m = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*([BbMm])$", s)
            if m:
                num = float(m.group(1))
                suf = m.group(2).upper()
                return int(num * (1_000_000_000 if suf == "B" else 1_000_000))
            try:
                return int(float(s))
            except Exception:
                return None

        def _humanize(n):
            if n is None:
                return None
            n = int(n)
            if n >= 1_000_000_000:
                x = n / 1_000_000_000
                s = f"{x:.1f}" if x < 10 else f"{int(round(x))}"
                if s.endswith(".0"):
                    s = s[:-2]
                return f"{s}B"
            if n >= 1_000_000:
                x = n / 1_000_000
                s = f"{x:.1f}" if x < 10 else f"{int(round(x))}"
                if s.endswith(".0"):
                    s = s[:-2]
                return f"{s}M"
            return f"{n:,}"

        param_candidate = None
        for key in ("parameter_size", "parameter_count"):
            if key in details:
                param_candidate = details.get(key)
                break
        if param_candidate is None:
            param_candidate = model_info.get("general.parameter_count")
        human = _humanize(_parse_param_count(param_candidate))

        size_label = model_info.get("general.size_label")
        size_label_norm = str(size_label).strip() if size_label else None

        tag = model_id.split(":", 1)[1].strip() if ":" in model_id else None

        if tag:
            tl = tag.lower()
            if tl in ("latest", "stable", "current"):
                suffix = f"{tag} · {human}" if human else tag
            else:
                m = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*([bBmM])$", tag)
                if m:
                    tag_size = f"{m.group(1)}{m.group(2).upper()}"
                    if size_label_norm and size_label_norm.upper() == tag_size.upper():
                        suffix = size_label_norm
                    else:
                        suffix = tag_size
                else:
                    suffix = f"{tag} · {human}" if human else tag
        else:
            if size_label_norm:
                suffix = size_label_norm
            elif human:
                suffix = human
            else:
                return model_id

        return f"{basename} ({suffix})"

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
                self.log.warning(f"{self.__class__.__name__}: failed to pull model {model_id} from {self.base_url}, status code {r.status_code}: {r.text}")

            return r.status_code == 200

        except requests.RequestException as e:
            if self.log:
                self.log.warning(f"{self.__class__.__name__}: failed to pull model {model_id} from {self.base_url}: {e}")

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
                self.log.warning(f"{self.__class__.__name__}: failed to delete model {model_id} from {self.base_url}, status code {r.status_code}: {r.text}")
            return r.status_code == 200
        except requests.RequestException as e:
            if self.log:
                self.log.warning(f"{self.__class__.__name__}: failed to delete model {model_id} from {self.base_url}: {e}")
            return False