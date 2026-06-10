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
		"""
		Manage LLM models and providers
		"""
		task = self.job.details.get("task", "refresh") if self.job.details else "refresh"
		provider = self.job.details.get("provider", "") if self.job.details else None
		model_name = self.job.data["remote_id"]
		providers = self.config.get("llm.providers", {})

		# pull/delete on the targeted connection(s). The `provider`
		# filter scopes the *action* only - never the inventory rebuild below.
		success = False
		for provider_id, provider_config in providers.items():
			if provider and provider != provider_id:
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
				success = client.pull_model(model_name) or success # in case a prior loop already succeeded
			elif task == "delete" and hasattr(client, "delete_model"):
				success = client.delete_model(model_name) or success # in case a prior loop already succeeded
			elif task != "refresh":
				self.log.warning(f"{self.__class__.__name__}: task '{task}' unknown or not supported by connection '{provider_id}'")

		if task != "refresh" and not success:
			# nothing changed and no explicit refresh requested - leave settings as-is
			self.job.finish()
			return

		# Rebuild available models inventory to reflect every
		# connection, regardless of which one an action targeted. 
		prev_available = self.config.get("llm.available_models", {}) or {}
		available_models = {}
		listed_connections = set()
		for provider_id, provider_config in providers.items():
			try:
				client = LLMProviderClient.get_client(self.config, provider_config)
			except ValueError:
				self.log.debug(f"{self.__class__.__name__}: invalid provider type: {provider_config['type']}, skipping")
				continue

			models = client.list_models()
			if not models:
				# unreachable, errored, or genuinely empty - indistinguishable, so
				# don't touch this connection's models. A transient outage must not
				# silently disable them; its entries are simply not refreshed now.
				self.log.warning(f"{self.__class__.__name__}: no models returned from connection '{provider_id}', leaving its models untouched")
				continue

			listed_connections.add(provider_id)
			for model in models:
				entry = client.build_model_entry(model)
				available_models[entry["id"]] = entry

		# Prune enabled models to what is available
		kept_enabled = []
		for model_id in self.config.get("llm.enabled_models", []):
			if model_id in available_models:
				kept_enabled.append(model_id)
				continue

			# only drop a model if its connection actually reported back this round. 
			connection = prev_available.get(model_id, {}).get("provider")
			if connection in providers and connection not in listed_connections:
				kept_enabled.append(model_id)

		self.config.set("llm.available_models", available_models)
		self.config.set("llm.enabled_models", kept_enabled)

		self.job.finish()
