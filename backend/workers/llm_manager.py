"""
Manage LLM models
"""
from backend.lib.worker import BasicWorker
from common.lib.llm.llm_client import LLMServerClient

class LLMServerManager(BasicWorker):
	"""
	Manages LLM models

	Periodically refreshes the list of available models from an LLM server.
	Can also pull or delete models on demand when queued with a specific task.

	Job details:
	  - task: "refresh" (default), "pull", or "delete"
	  - server: the URL of the LLM server, as configured in the
	    llm.servers setting. if not given, run on all servers

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
		Manage LLM models and servers
		"""
		task = self.job.details.get("task", "refresh") if self.job.details else "refresh"
		server = self.job.details.get("server", "") if self.job.details else None
		model_name = self.job.data["remote_id"]
		servers = self.config.get("llm.servers", {})
		current_models = self.config.get("llm.available_models", {})

		# pull/delete on the targeted connection(s). The `provider`
		# filter scopes the *action* only - never the inventory rebuild below.
		changes_made = False
		for server_id, server_config in servers.items():
			if server and server != server_id:
				continue

			try:
				client = LLMServerClient.get_client(self.config, server_config, self.log)
			except ValueError:
				self.log.debug(f"{self.__class__.__name__}: invalid server type: {server_config['type']}, skipping")
				continue

			# note that technically it is possible to pull/delete a model on
			# multiple servers at once (if a model_name is defined but no
			# server). may not be a problem? may be useful one day?
			if task == "pull" and hasattr(client, "pull_model"):
				changes_made = client.pull_model(model_name) or changes_made # in case a prior loop already succeeded
			elif task == "delete":
				if hasattr(client, "delete_model") and model_name in current_models:
					model_info = current_models.get(model_name, {})
					changes_made = client.delete_model(model_info["local_id"]) or changes_made # in case a prior loop already succeeded
			elif task != "refresh":
				self.log.warning(f"{self.__class__.__name__}: task '{task}' unknown or not supported by connection '{server_id}'")

		if task != "refresh" and not changes_made:
			# nothing changed and no explicit refresh requested - leave settings as-is
			self.job.finish()
			return

		# Rebuild available models inventory to reflect every
		# connection, regardless of which one an action targeted. 
		prev_available = self.config.get("llm.available_models", {}) or {}
		available_models = {}
		listed_connections = set()
		for server_id, server_config in servers.items():
			try:
				client = LLMServerClient.get_client(self.config, server_config, self.log)
			except ValueError:
				self.log.debug(f"{self.__class__.__name__}: invalid server type: {server_config['type']}, skipping")
				continue

			models = client.list_models()
			if not models:
				# unreachable, errored, or genuinely empty - indistinguishable, so
				# don't touch this connection's models. A transient outage must not
				# silently disable them; its entries are simply not refreshed now.
				self.log.warning(f"{self.__class__.__name__}: no models returned from connection '{server_id}', leaving its models untouched")
				continue

			listed_connections.add(server_id)
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
			connection = prev_available.get(model_id, {}).get("server")
			if connection in servers and connection not in listed_connections:
				kept_enabled.append(model_id)

		self.config.set("llm.available_models", available_models)
		self.config.set("llm.enabled_models", kept_enabled)

		self.job.finish()
