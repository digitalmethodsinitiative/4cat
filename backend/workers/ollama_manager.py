"""
Manage Ollama LLM models
"""
from backend.lib.worker import BasicWorker
from common.lib.ollama_client import OllamaClient


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
	client = None

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

	def _get_client(self) -> OllamaClient:
		"""Return a fresh OllamaClient configured from 4CAT settings."""
		if not self.client:
			self.client = OllamaClient.from_config(self.config)
		return self.client

	def refresh_models(self):
		"""
		Query the Ollama server for available models and update llm.available_models.
		"""
		if not self.config.get("llm.server", ""):
			return

		client = self._get_client()
		models = client.list_models()

		if not models and not self.config.get("llm.server", ""):
			return

		available_models = {}
		for model in models:
			model_id = model["name"]
			meta = client.show_model(model_id)
			if meta:
				try:
					display_name = OllamaClient.format_display_name(model_id, meta)
				except Exception as e:
					self.log.debug(f"OllamaManager: error formatting display name for {model_id}: {e}")
					display_name = model_id
			else:
				self.log.debug(f"OllamaManager: could not get metadata for {model_id}, using name only")
				display_name = model_id

			available_models[model_id] = OllamaClient.build_model_entry(model_id, display_name, meta)

		self.config.set("llm.available_models", available_models)
		self.log.debug(f"OllamaManager: refreshed model list ({len(available_models)} models)")

		# Reconcile enabled models: remove any that are no longer available
		enabled_models = self.config.get("llm.enabled_models", [])
		reconciled = [m for m in enabled_models if m in available_models]
		if len(reconciled) != len(enabled_models):
			removed = set(enabled_models) - set(reconciled)
			self.log.info(f"OllamaManager: removed stale enabled model(s): {', '.join(removed)}")
			self.config.set("llm.enabled_models", reconciled)

	def pull_model(self, model_name):
		"""
		Pull a model from the Ollama registry.

		:param str model_name:  Model name (e.g. "llama3:8b")
		:return bool:  True on success
		"""
		if not self.config.get("llm.server", ""):
			self.log.warning("OllamaManager: cannot pull model - no LLM server configured")
			return False

		success = self._get_client().pull_model(model_name)
		if success:
			self.log.info(f"OllamaManager: successfully pulled model '{model_name}'")
		else:
			self.log.warning(f"OllamaManager: could not pull model '{model_name}'")
		return success

	def delete_model(self, model_name):
		"""
		Delete a model from the Ollama server.

		:param str model_name:  Model name (e.g. "llama3:8b")
		:return bool:  True on success
		"""
		if not self.config.get("llm.server", ""):
			self.log.warning("OllamaManager: cannot delete model - no LLM server configured")
			return False

		success = self._get_client().delete_model(model_name)
		if success:
			self.log.info(f"OllamaManager: successfully deleted model '{model_name}'")
		else:
			self.log.warning(f"OllamaManager: could not delete model '{model_name}'")
		return success
