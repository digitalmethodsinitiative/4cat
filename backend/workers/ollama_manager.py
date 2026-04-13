"""
Manage Ollama LLM models
"""
import json
import requests
import re

from backend.lib.worker import BasicWorker


class OllamaManager(BasicWorker):
    """
    Manage Ollama LLM models

    Periodically refreshes the list of available models from an Ollama server.
    Can also pull or delete models on demand when queued with a specific task.

    Job details:
      - task: "refresh" (default), "pull", or "delete"

    Job remote_id:
      - For refresh: "manage-ollama-refresh" (periodic) or "manage-ollama-manual" (on-demand)
      - For pull/delete: the model name to pull or delete
    """
    type = "manage-ollama"
    max_workers = 1

    @classmethod
    def ensure_job(cls, config=None):
        """
        Ensure the daily refresh job is always scheduled

        :return:  Job parameters for the worker
        """
        return {"remote_id": "manage-ollama-refresh", "interval": 86400}

    def work(self):
        task = self.job.details.get("task", "refresh") if self.job.details else "refresh"
        model_name = self.job.data["remote_id"]

        if task == "refresh":
            self.refresh_models()
        elif task == "pull":
            success = self.pull_model(model_name)
            if success:
                self.refresh_models()
        elif task == "delete":
            success = self.delete_model(model_name)
            if success:
                self.refresh_models()
        else:
            self.log.warning(f"OllamaManager: unknown task '{task}'")

        self.job.finish()

    def _get_llm_headers(self):
        """Build request headers for LLM server auth."""
        headers = {"Content-Type": "application/json"}
        llm_api_key = self.config.get("llm.api_key", "")
        llm_auth_type = self.config.get("llm.auth_type", "")
        if llm_api_key and llm_auth_type:
            headers[llm_auth_type] = llm_api_key
        return headers

    @staticmethod
    def _format_model_display_name(model_id, meta):
        """
        Build a friendly display name for a model using metadata where possible.
        Falls back to a sensible string derived from `model_id`.

        Dear Ollama: if you add a "display_name" field to your /api/show response, I will use it and not complain about missing metadata fields.  Pretty please? :)
        Because this is ridiculous.
        """
        model_info = meta.get("model_info", {}) if meta else {}
        details = meta.get("details", {}) if meta else {}

        # Basename preference: explicit metadata, else model id prefix
        basename = None
        for key in ("general.basename", "general.base_model.0.name"):
            val = model_info.get(key)
            if val:
                basename = str(val).strip()
                break
        if not basename:
            basename = model_id.split(":", 1)[0].replace("-", " ").replace("_", " ").strip() or model_id

        # Helpers for parsing and formatting parameter counts
        def _parse_param_count(val):
            if val is None:
                return None
            if isinstance(val, int):
                return val
            if isinstance(val, float):
                return int(val)
            s = str(val).strip()
            if not s:
                return None
            s = s.replace(",", "")
            m = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*([BbMm])$", s)
            if m:
                num = float(m.group(1))
                suf = m.group(2).upper()
                return int(num * (1_000_000_000 if suf == "B" else 1_000_000))
            # try float / scientific
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
                if s.endswith('.0'):
                    s = s[:-2]
                return f"{s}B"
            if n >= 1_000_000:
                x = n / 1_000_000
                s = f"{x:.1f}" if x < 10 else f"{int(round(x))}"
                if s.endswith('.0'):
                    s = s[:-2]
                return f"{s}M"
            return f"{n:,}"

        # Determine param count from prioritized fields
        param_candidate = None
        for key in ("parameter_size", "parameter_count"):
            if key in details:
                param_candidate = details.get(key)
                break
        if param_candidate is None:
            param_candidate = model_info.get("general.parameter_count")
        param_int = _parse_param_count(param_candidate)
        human = _humanize(param_int)

        # Normalize size label if present
        size_label = model_info.get("general.size_label")
        size_label_norm = str(size_label).strip() if size_label else None

        # Extract tag (suffix after ':') if present
        tag = model_id.split(":", 1)[1].strip() if ":" in model_id else None

        # Decide suffix using tag-aware rules
        suffix = None
        if tag:
            t = tag
            tl = t.lower()
            # Special handling for common tags that often indicate size or version
            if tl in ("latest", "stable", "current"):
                suffix = f"{t} · {human}" if human else t
            # If tag looks like a size (e.g. "1b", "1.7B"), can use as suffix
            else:
                m = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*([bBmM])$", t)
                if m:
                    # tag is a size like '1b' or '1.7B'
                    num = m.group(1)
                    suf = m.group(2).upper()
                    tag_size = f"{num}{suf}"
                    # prefer explicit size_label if it matches
                    if size_label_norm and size_label_norm.upper() == tag_size.upper():
                        suffix = size_label_norm
                    else:
                        suffix = tag_size
                else:
                    suffix = f"{t} · {human}" if human else t
        else:
            # No tag, so just use size if available
            if size_label_norm:
                suffix = size_label_norm
            elif human:
                suffix = human
            else:
                # Nothing useful to show; fallback to model id
                return model_id

        return f"{basename} ({suffix})"

    def refresh_models(self):
        """
        Query the Ollama server for available models and update llm.available_models.
        """
        llm_server = self.config.get("llm.server", "")
        if not llm_server:
            return

        headers = self._get_llm_headers()
        available_models = {}

        try:
            response = requests.get(f"{llm_server}/api/tags", headers=headers, timeout=10)
        except requests.RequestException as e:
            self.log.warning(f"OllamaManager: could not refresh model list - request error: {e}")
            return

        if response.status_code != 200:
            self.log.warning(f"OllamaManager: could not refresh model list - server returned {response.status_code}")
            return

        for model in response.json().get("models", []):
            model_id = model["name"]
            try:
                meta = self.get_model_metadata(model_id)
            except (requests.RequestException, json.JSONDecodeError, KeyError) as e:
                self.log.debug(f"OllamaManager: could not get metadata for {model_id} (error: {e}), using name only")
                meta = None
            if meta:
                try:
                    display_name = self._format_model_display_name(model_id, meta)
                except Exception as e:
                    self.log.debug(f"OllamaManager: error formatting display name for {model_id}: {e}")
                    display_name = model_id
                success = True
            else:
                display_name = model_id
                meta = {}
                success = False

            available_models[model_id] = {
                "name": display_name,
                "model_card": f"https://ollama.com/library/{model_id.split(':')[0]}",
                "provider": "local",
                "metadata_success": success,
                "model_info": meta.get("model_info", {}),
                "capabilities": meta.get("capabilities", []),
                "details": meta.get("details", {}),
                "modified_at": meta.get("modified_at", None),
            }

        self.config.set("llm.available_models", available_models)
        self.log.debug(f"OllamaManager: refreshed model list ({len(available_models)} models)")

        # Reconcile enabled models: remove any that are no longer available
        enabled_models = self.config.get("llm.enabled_models", [])
        reconciled = [m for m in enabled_models if m in available_models]
        if len(reconciled) != len(enabled_models):
            removed = set(enabled_models) - set(reconciled)
            self.log.info(f"OllamaManager: removed stale enabled model(s): {', '.join(removed)}")
            self.config.set("llm.enabled_models", reconciled)


    def get_model_metadata(self, model_name):
        """
        Get metadata for a specific model from the Ollama server.

        :param str model_name:  Model name (e.g. "llama3:8b")
        :return dict or None:  Metadata dict on success, None on failure
        """
        llm_server = self.config.get("llm.server", "")
        if not llm_server:
            self.log.warning("OllamaManager: cannot get model metadata - no LLM server configured")
            return None

        headers = self._get_llm_headers()
        try:
            response = requests.post(
                f"{llm_server}/api/show",
                headers=headers,
                json={"model": model_name},
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            else:
                self.log.warning(f"OllamaManager: could not get metadata for model '{model_name}' - server returned {response.status_code}")
                return None
        except requests.RequestException as e:
            self.log.warning(f"OllamaManager: could not get metadata for model '{model_name}' - request error: {e}")
            return None

    def pull_model(self, model_name):
        """
        Pull a model from the Ollama registry.

        :param str model_name:  Model name (e.g. "llama3:8b")
        :return bool:  True on success
        """
        llm_server = self.config.get("llm.server", "")
        if not llm_server:
            self.log.warning("OllamaManager: cannot pull model - no LLM server configured")
            return False

        headers = self._get_llm_headers()
        try:
            # stream=False waits for the pull to complete before returning
            response = requests.post(
                f"{llm_server}/api/pull",
                headers=headers,
                json={"model": model_name, "stream": False},
                timeout=600
            )
            if response.status_code == 200:
                self.log.info(f"OllamaManager: successfully pulled model '{model_name}'")
                return True
            else:
                self.log.warning(f"OllamaManager: could not pull model '{model_name}' - server returned {response.status_code}")
                return False
        except requests.RequestException as e:
            self.log.warning(f"OllamaManager: could not pull model '{model_name}' - request error: {e}")
            return False

    def delete_model(self, model_name):
        """
        Delete a model from the Ollama server.

        :param str model_name:  Model name (e.g. "llama3:8b")
        :return bool:  True on success
        """
        llm_server = self.config.get("llm.server", "")
        if not llm_server:
            self.log.warning("OllamaManager: cannot delete model - no LLM server configured")
            return False

        headers = self._get_llm_headers()
        try:
            response = requests.delete(
                f"{llm_server}/api/delete",
                headers=headers,
                json={"model": model_name},
                timeout=30
            )
            if response.status_code == 200:
                self.log.info(f"OllamaManager: successfully deleted model '{model_name}'")
                return True
            else:
                self.log.warning(f"OllamaManager: could not delete model '{model_name}' - server returned {response.status_code}")
                return False
        except requests.RequestException as e:
            self.log.warning(f"OllamaManager: could not delete model '{model_name}' - request error: {e}")
            return False
