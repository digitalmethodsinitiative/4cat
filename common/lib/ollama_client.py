"""
Centralized HTTP client for communicating with an Ollama server.

This class owns all direct HTTP calls to Ollama's REST API and provides shared static
helpers for capability parsing, display-name formatting, and building canonical
llm.available_models entries. It is a plain helper with no 4CAT base-class dependency.
"""

import re
import requests

from typing import Optional


class OllamaClient:
    """
    HTTP client for an Ollama server.

    :param base_url:    Base URL of the Ollama server (e.g. "http://localhost:11434").
    :param api_key:     Optional API key for authentication.
    :param auth_type:   Header name to use for the API key (e.g. "Authorization").
    :param timeout:     Default request timeout in seconds.
    """

    def __init__(self, base_url: str, api_key: Optional[str] = None,
                 auth_type: Optional[str] = None, timeout: int = 10, log=None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.auth_type = auth_type
        self.timeout = timeout
        self._session = requests.Session()
        self.log = log

    def _headers(self) -> dict:
        """Build request headers, including auth if configured."""
        headers = {"Content-Type": "application/json"}
        if self.api_key and self.auth_type:
            headers[self.auth_type] = self.api_key
        return headers
    
    def is_available(self) -> bool:
        """Check if the Ollama server is reachable and responding to /api/tags."""
        try:
            r = self._session.get(
                f"{self.base_url}/api/tags",
                headers=self._headers(),
                timeout=self.timeout,
            )
            if self.log and r.status_code != 200:
                self.log.warning(f"OllamaClient: server responded with status code {r.status_code} during availability check: {r.text}")
            return r.status_code == 200
        except requests.RequestException as e:
            if self.log:
                self.log.warning(f"OllamaClient: server is not available at {self.base_url}: {e}")
            return False

    def list_models(self) -> list[dict]:
        """List available models from the Ollama server.

        :returns:   List of model dicts from ``/api/tags``, or ``[]`` on failure.
        """
        try:
            r = self._session.get(
                f"{self.base_url}/api/tags",
                headers=self._headers(),
                timeout=self.timeout,
            )
            if r.status_code == 200:
                return r.json().get("models", [])
            if self.log:
                self.log.warning(f"OllamaClient: failed to list models from {self.base_url}, status code {r.status_code}: {r.text}")
        except requests.RequestException as e:
            if self.log:
                self.log.warning(f"OllamaClient: failed to list models from {self.base_url}: {e}")
        return []

    def show_model(self, model_id: str) -> dict | None:
        """Fetch full metadata for a model via ``POST /api/show``.

        :param model_id:    Model name (e.g. ``"llama3:8b"``).
        :returns:           Parsed response dict, or ``None`` on failure.
        """
        try:
            r = self._session.post(
                f"{self.base_url}/api/show",
                headers=self._headers(),
                json={"model": model_id},
                timeout=self.timeout,
            )
            if r.status_code == 200:
                return r.json()
            if self.log:
                self.log.warning(f"OllamaClient: failed to show model {model_id} from {self.base_url}, status code {r.status_code}: {r.text}")
        except requests.RequestException as e:
            if self.log:
                self.log.warning(f"OllamaClient: failed to show model {model_id} from {self.base_url}: {e}")
        return None

    def pull_model(self, model_id: str, stream: bool = False) -> bool:
        """Pull a model from the Ollama registry.

        :param model_id:    Model name (e.g. ``"llama3:8b"``).
        :param stream:      Whether to stream the response (default ``False``).
        :returns:           ``True`` on success, ``False`` on failure.
        """
        try:
            r = self._session.post(
                f"{self.base_url}/api/pull",
                headers=self._headers(),
                json={"model": model_id, "stream": stream},
                timeout=600,
            )
            if r.status_code != 200 and self.log:
                self.log.warning(f"OllamaClient: failed to pull model {model_id} from {self.base_url}, status code {r.status_code}: {r.text}")
            return r.status_code == 200
        except requests.RequestException as e:
            if self.log:
                self.log.warning(f"OllamaClient: failed to pull model {model_id} from {self.base_url}: {e}")
            return False

    def delete_model(self, model_id: str) -> bool:
        """Delete a model from the Ollama server.

        :param model_id:    Model name (e.g. ``"llama3:8b"``).
        :returns:           ``True`` on success, ``False`` on failure.
        """
        try:
            r = self._session.delete(
                f"{self.base_url}/api/delete",
                headers=self._headers(),
                json={"model": model_id},
                timeout=30,
            )
            if r.status_code != 200 and self.log:
                self.log.warning(f"OllamaClient: failed to delete model {model_id} from {self.base_url}, status code {r.status_code}: {r.text}")
            return r.status_code == 200
        except requests.RequestException as e:
            if self.log:
                self.log.warning(f"OllamaClient: failed to delete model {model_id} from {self.base_url}: {e}")  
            return False

    @staticmethod
    def parse_supported_media_types(meta: dict | None) -> list[str]:
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

    @staticmethod
    def format_display_name(model_id: str, meta: dict | None) -> str:
        """Build a human-readable display name for a model.

        Logic is identical to the legacy ``OllamaManager._format_model_display_name``
        and has been moved here so it can be shared across OllamaManager and any
        other caller without importing the worker class.

        :param model_id:    Raw Ollama model identifier (e.g. ``"llama3:8b"``).
        :param meta:        ``/api/show`` response dict, or ``None``.
        :returns:           Human-readable display name string.
        """
        model_info = meta.get("model_info", {}) if meta else {}
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

        suffix = None
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

    @staticmethod
    def build_model_entry(model_id: str, display_name: str, meta: dict | None) -> dict:
        """Build a canonical ``llm.available_models`` entry for a model.

        :param model_id:        Raw Ollama model identifier.
        :param display_name:    Human-readable name (from ``format_display_name``).
        :param meta:            ``/api/show`` response dict, or ``None`` if unavailable.
        :returns:               Dict ready to store under ``llm.available_models[model_id]``.
        """
        has_meta = bool(meta)
        return {
            "name": display_name,
            "model_card": f"https://ollama.com/library/{model_id.split(':')[0]}",
            "provider": "local",
            "metadata_success": has_meta,
            "model_info": meta.get("model_info", {}) if has_meta else {},
            "capabilities": meta.get("capabilities", []) if has_meta else [],
            "details": meta.get("details", {}) if has_meta else {},
            "modified_at": meta.get("modified_at", None) if has_meta else None,
            "supported_media_types": OllamaClient.parse_supported_media_types(meta),
        }

    @classmethod
    def from_config(cls, config, log=None) -> "OllamaClient":
        """Instantiate an OllamaClient from 4CAT config.

        Reads ``llm.server``, ``llm.api_key``, and ``llm.auth_type``.

        :param config:  A 4CAT ``ConfigWrapper`` or ``ConfigManager`` instance.
        :param log:     A logging instance for reporting issues.
        :returns:       Configured ``OllamaClient``.
        """
        return cls(
            base_url=config.get("llm.server", ""),
            api_key=config.get("llm.api_key", "") or None,
            auth_type=config.get("llm.auth_type", "") or None,
            log=log,
        )
