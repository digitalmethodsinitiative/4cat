"""
Refresh items
"""
from backend.lib.worker import BasicWorker

class ItemUpdater(BasicWorker):
    """
    Refresh 4CAT items

    Refreshes settings that are dependent on external factors.
    LLM model refreshing is handled by the OllamaManager worker.
    """
    type = "refresh-items"
    max_workers = 1

    # ensure_job is intentionally disabled: this worker currently does nothing
    # and would only create unnecessary job queue churn. Re-enable when work()
    # has actual tasks to perform.
    # @classmethod
    # def ensure_job(cls, config=None):
    #     return {"remote_id": "refresh-items", "interval": 60}

    def work(self):
        # Placeholder – no tasks implemented yet.
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

            available_models = {}
            try:
                response = requests.get(f"{llm_server}/api/tags", headers=headers, timeout=10)
                if response.status_code == 200:
                    settings = response.json()
                    for model in settings.get("models", []):
                        model = model["name"]
                        try:
                            model_metadata = requests.post(f"{llm_server}/api/show", headers=headers, json={"model": model}, timeout=10).json()
                            available_models[model] = {
                                "name": f"{model_metadata['model_info'].get('general.basename', model)} ({model_metadata['details']['parameter_size']} parameters)",
                                "model_card": f"https://ollama.com/library/{model}",
                                "provider": "local"
                            }
                            
                        except (requests.RequestException, json.JSONDecodeError, KeyError) as e:
                            self.log.debug(f"Could not get metadata for model {model} from Ollama - skipping (error: {e})")

                    self.config.set("llm.available_models", available_models)
                    self.log.debug("Refreshed LLM server settings cache")
                else:
                    self.log.warning(f"Could not refresh LLM server settings cache - server returned status code {response.status_code}")

            except requests.RequestException as e:
                self.log.warning(f"Could not refresh LLM server settings cache - request error: {str(e)}")
            