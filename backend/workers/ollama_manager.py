"""
Manage Ollama LLM models
"""
import json
import requests

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
            if response.status_code != 200:
                self.log.warning(f"OllamaManager: could not refresh model list - server returned {response.status_code}")
                return

            for model in response.json().get("models", []):
                model_id = model["name"]
                try:
                    meta = requests.post(
                        f"{llm_server}/api/show",
                        headers=headers,
                        json={"model": model_id},
                        timeout=10
                    ).json()
                    display_name = (
                        f"{meta['model_info']['general.basename']}"
                        f" ({meta['details']['parameter_size']} parameters)"
                    )
                except (requests.RequestException, json.JSONDecodeError, KeyError) as e:
                    self.log.debug(f"OllamaManager: could not get metadata for {model_id} (error: {e}), using name only")
                    display_name = model_id

                available_models[model_id] = {
                    "name": display_name,
                    "model_card": f"https://ollama.com/library/{model_id.split(':')[0]}",
                    "provider": "local"
                }

            self.config.set("llm.available_models", available_models)
            self.log.debug(f"OllamaManager: refreshed model list ({len(available_models)} models)")

        except requests.RequestException as e:
            self.log.warning(f"OllamaManager: could not refresh model list - request error: {e}")

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
