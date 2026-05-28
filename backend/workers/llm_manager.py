"""
Manage LLM models
"""
from backend.lib.worker import BasicWorker
from common.lib.llm.llm_client import LLMProviderClient

class LLMProviderManager(BasicWorker):
	"""
	Manages LLM models

	Periodically refreshes the list of available models from an LLM provider.
	Can also pull or delete models on demand when queued with a specific task.

	Job details:
	  - task: "refresh" (default), "pull", or "delete"
	  - provider: the URL of the LLM provider, as configured in the
	    llm.providers setting. if not given, run on all providers

	Job remote_id:
	  - For refresh: "manage-llm-refresh" (periodic) or "manage-llm-manual" (on-demand)
	  - For pull/delete: the model name to pull or delete
	"""
	type = "manage-llm"
	max_workers = 1
	client = None

	@classmethod
	def ensure_job(cls, config=None):
		"""
		Ensure the daily refresh job is always scheduled

		:return:  Job parameters for the worker
		"""
		return {"remote_id": "manage-llm-refresh", "interval": 86400}

	def work(self):
		task = self.job.details.get("task", "refresh") if self.job.details else "refresh"
		provider = self.job.details.get("provider", "") if self.job.details else None
		model_name = self.job.data["remote_id"]
		available_models = None

		for provider_config in self.config.get("llm.providers", []):
			if provider and provider != provider_config["url"]:
				continue

			try:
				client = LLMProviderClient.get_client(self.config, provider_config)
			except ValueError:
				self.log.debug(f"{self.__class__.__name__}: invalid provider type: {provider_config['type']}, skipping")
				continue

			# note that technically it is possible to pull/delete a model on
			# multiple providers at once (if a model_name is defined but no
			# provider). may not be a problem? may be useful one day?
			success = False
			if task == "pull" and hasattr(client, "pull_model"):
				success = client.pull_model(model_name)

			elif task == "delete" and hasattr(client, "delete_model"):
				success = client.delete_model(model_name)

			if success or task == "refresh":
				# refresh models after pulling/deleting, or when asked to
				if available_models is None:
					available_models = {}

				for model in client.list_models():
					model = client.build_model_entry(model)
					available_models[model["id"]] = model

				self.log.debug(f"{self.__class__.__name__}: ran task '{task}' (model name: {model_name or 'N/A'})")

			elif success is None:
				self.log.warning(f"{self.__class__.__name__}: task '{task}' unknown or not supported by client")
			else:
				self.log.warning(f"{self.__class__.__name__}: task '{task}' failed for model {model_name}")

		if available_models is not None:
			enabled_and_available = set(available_models.keys()) & set(self.config.get("llm.enabled_models", []))
			self.config.set("llm.available_models", available_models)
			self.config.set("llm.enabled_models", list(enabled_and_available))

		self.job.finish()
