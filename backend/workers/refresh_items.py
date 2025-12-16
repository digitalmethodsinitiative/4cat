"""
Refresh items
"""
import requests

from backend.lib.worker import BasicWorker

class ItemUpdater(BasicWorker):
    """
    Refresh 4CAT items

    Refreshes settings that are dependent on external factors
    """
    type = "refresh-items"
    max_workers = 1

    @classmethod
    def ensure_job(cls, config=None):
        """
        Ensure that the refresher is always running

        This is used to ensure that the refresher is always running, and if it is
        not, it will be started by the WorkerManager.

        :return:  Job parameters for the worker
        """
        return {"remote_id": "refresh-items", "interval": 60}

    def work(self):
        # Refresh items
        self.refresh_settings()

        self.job.finish()

    def refresh_settings(self):
        """
        Refresh settings
        """
        # LLM server settings
        llm_provider = self.config.get("llm.provider_type", "none").lower()
        llm_server = self.config.get("llm.server", "")

        # For now we only support the Ollama API
        if llm_provider == "ollama" and llm_server:
            headers = {"Content-Type": "application/json"}
            llm_api_key = self.config.get("llm.api_key", "")
            llm_auth_type = self.config.get("llm.auth_type", "")
            if llm_api_key and llm_auth_type:
                headers[llm_auth_type] = llm_api_key

            try:
                response = requests.get(f"{llm_server}/api/tags", headers=headers, timeout=10)
                if response.status_code == 200:
                    settings = response.json()
                    self.config.set("llm.available_models", settings.get("models", []))
                    self.log.debug("Refreshed LLM server settings cache")
                else:
                    self.log.warning(f"Could not refresh LLM server settings cache - server returned status code {response.status_code}")

            except requests.RequestException as e:
                self.log.warning(f"Could not refresh LLM server settings cache - request error: {str(e)}")
            