"""
Load modules and datasources dynamically
"""
from pathlib import Path
import importlib
import inspect
import config
import pickle
import sys
import re
import os

from backend.abstract.worker import BasicWorker
from backend.abstract.processor import BasicProcessor


class ModuleCollector:
	"""
	Collects all modular appendages of 4CAT

	On init, an object of this class collects all datasources and workers that
	have been added to this 4CAT installation. The metadata of these is then
	stored for later access.

	Datasources are found in the "datasources" folder in root. Workers are
	found in datasource folders or the default "backend/processors" and
	"backend/workers" folder. All these folders are scanned for both
	processors and workers (processors being a specific kind of worker).
	"""
	ignore = []
	missing_modules = {}

	PROCESSOR = 1
	WORKER = 2

	workers = {}
	processors = {}
	datasources = {}

	def __init__(self):
		"""
		Load data sources and workers

		Datasources are loaded first so that the datasource folders may be
		scanned for workers subsequently.
		"""

		# try to load module data from cache
		cached_modules = self.load_from_cache()
		if cached_modules:
			self.datasources = cached_modules["datasources"]
			self.workers = cached_modules["workers"]
			self.processors = cached_modules["processors"]
			return

		# no cache available, regenerate...
		self.regenerate_cache()

	def regenerate_cache(self):
		"""
		Load all module data from disk and cache results
		"""
		self.load_datasources()
		self.load_modules()
		self.cache()

	@staticmethod
	def is_4cat_class(object):
		"""
		Determine if a module member is a Search class we can use
		"""
		return inspect.isclass(object) and \
			   issubclass(object, BasicWorker) and \
			   object is not BasicWorker and \
			   not inspect.isabstract(object)

	def load_modules(self):
		"""
		Load modules

		Modules are workers and (as a subset of workers) postprocessors. These
		are found by importing any python files found in the given locations,
		and looking for relevant classes within those python files, that extend
		`BasicProcessor` or `BasicWorker` and are not abstract.
		"""
		# look for workers and processors in pre-defined folders and datasources

		paths = [Path(config.PATH_ROOT, "processors"), Path(config.PATH_ROOT, "backend", "workers"),
				 *[self.datasources[datasource]["path"] for datasource in self.datasources]]

		root_match = re.compile(r"^%s" % re.escape(config.PATH_ROOT))
		root_path = Path(config.PATH_ROOT)

		for folder in paths:
			# loop through folders, and files in those folders, recursively
			for file in folder.rglob("*.py"):
				# determine module name for file
				# reduce path to be relative to 4CAT root
				module_name = ".".join(file.parts[len(root_path.parts):-1] + (file.stem,))

				# check if we've already loaded this module
				if module_name in sys.modules or module_name in self.ignore:
					continue

				# try importing
				try:
					module = importlib.import_module(module_name)
				except ImportError as e:
					# this is fine, just ignore this data source and give a heads up
					self.ignore.append(module_name)
					if e.name not in self.missing_modules:
						self.missing_modules[e.name] = [module_name]
					else:
						self.missing_modules[e.name].append(module_name)
					continue

				# see if module contains the right type of content by looping
				# through all of its members
				components = inspect.getmembers(module, predicate=self.is_4cat_class)
				for component in components:
					if component[1].type in self.workers:
						# already indexed
						continue

					# extract data that is useful for the scheduler and other
					# parts of 4CAT
					relative_path = root_match.sub("", str(file))
					metadata = {
						"file": file.name,
						"path": relative_path,
						"module": relative_path[1:-3].replace(os.sep, "."),
						"id": component[1].type,
						"name": component[0],
						"class_name": component[0],
						"max": component[1].max_workers
					}

					# processors have some extra metadata that is useful to store
					if issubclass(component[1], BasicProcessor):
						metadata = {**metadata, **{
							"description": component[1].description,
							"name": component[1].title if hasattr(component[1], "title") else component[0],
							"extension": component[1].extension,
							"category": component[1].category if hasattr(component[1], "category") else "other",
							"accepts": component[1].accepts if hasattr(component[1], "accepts") else [],
							"options": component[1].options if hasattr(component[1], "options") else {},
							"datasources": component[1].datasources if hasattr(component[1], "datasources") else [],
							"references": component[1].references if hasattr(component[1], "references") else [],
							"is_filter": hasattr(component[1], "category") and "filter" in component[1].category.lower(),
							"further": [],
							"further_flat": set()
						}}

						# maintain a separate cache of processors
						self.processors[metadata["id"]] = metadata

					self.workers[metadata["id"]] = metadata

		sorted_processors = {id: self.processors[id] for id in
						   sorted(self.processors, key=lambda item: self.processors[item]["name"])}
		categorised_processors = {id: sorted_processors[id] for id in
						   sorted(sorted_processors, key=lambda item: "0" if sorted_processors[item]["category"] == "Presets" else sorted_processors[item]["category"])}

		# determine what processors are available as a follow-up for each
		# processor. This can only be done here because we need to know all
		# possible processors before we can inspect mutual compatibilities
		backup = categorised_processors.copy()
		for type in categorised_processors:
			categorised_processors[type]["further"] = []
			for possible_child in backup:
				if type in backup[possible_child]["accepts"]:
					categorised_processors[type]["further"].append(possible_child)

		self.processors = categorised_processors

		flat_further = set()
		def collapse_flat_list(processor):
			for further_processor in processor["further"]:
				if further_processor not in flat_further:
					collapse_flat_list(self.processors[further_processor])
					flat_further.add(further_processor)

		for processor in self.processors:
			flat_further = set()
			collapse_flat_list(self.processors[processor])
			self.processors[processor]["further_flat"] = flat_further

		# Give a heads-up if not all modules were installed properly.
		if self.missing_modules:
			print_msg = "Warning: Not all modules could be found, which might cause data sources and modules to not function.\nMissing modules:\n"
			for missing_module, processor_list in self.missing_modules.items():
				print_msg += "\t%s (for processors %s)\n" % (missing_module, ", ".join(processor_list))

			print(print_msg, file=sys.stderr)

		# Cache data
		self.cache()

	def load_datasources(self):
		"""
		Load datasources

		This looks for folders within the datasource root folder that contain
		an `__init__.py` defining an `init_datasource` function and a
		`DATASOURCE` constant. The latter is taken as the ID for this
		datasource.
		"""
		for subdirectory in Path(config.PATH_ROOT, "datasources").iterdir():
			# folder name, also the name used in config.py
			folder_name = subdirectory.parts[-1]

			# determine module name
			module_name = "datasources." + folder_name
			try:
				datasource = importlib.import_module(module_name)
			except ImportError as e:
				continue

			if not hasattr(datasource, "init_datasource") or not hasattr(datasource, "DATASOURCE"):
				continue

			datasource_id = datasource.DATASOURCE

			if datasource_id not in config.DATASOURCES:
				# not configured, so we're going to just ignore it
				continue

			self.datasources[datasource_id] = {
				"expire-datasets": config.DATASOURCES[datasource_id].get("expire-datasets", None),
				"path": subdirectory,
				"name": datasource.NAME if hasattr(datasource, "NAME") else datasource_id,
				"id": subdirectory.parts[-1],
				"init": datasource.init_datasource,
				"is_static": hasattr(datasource, "IS_STATIC") and datasource.IS_STATIC
			}

		sorted_datasources = {datasource_id: self.datasources[datasource_id] for datasource_id in sorted(self.datasources, key=lambda id: self.datasources[id]["name"])}
		self.datasources = sorted_datasources

	def cache(self):
		"""
		Write module data to cache file

		The cache is written to disk, not kept in memory, because e.g. the
		web tool and backend don't share memory, but can still use the same
		cache as it should only be refreshed when the back end restarts,
		since else you'd get processors in the web tool that aren't known
		to the back end yet
		"""
		with ModuleCollector.get_cache_path().open("wb") as output:
			pickle.dump({
				"datasources": self.datasources,
				"workers": self.workers,
				"processors": self.processors
			}, output)

	def load_from_cache(self):
		"""
		Load module data from cache

		:return: Dictionary with `datasources`, `workers` and `processors`
		keys, or None if no cached data is available
		"""
		cache_path = ModuleCollector.get_cache_path()

		if not cache_path.exists():
			return None

		try:
			return pickle.load(cache_path.open("rb"))
		except pickle.UnpicklingError:
			return None

	def load_worker_class(self, worker):
		"""
		Get class for worker

		This import worker modules on-demand, so the code is only loaded if a
		worker that needs the code is actually queued and run

		:return:  Worker class for the given worker metadata
		"""
		module = worker["module"]
		if module not in sys.modules:
			importlib.import_module(module)

		return getattr(sys.modules[module], worker["class_name"])

	@staticmethod
	def get_cache_path():
		"""
		Get path to module cache file

		:return Path:  Path object to cache file
		"""
		return Path(config.PATH_ROOT, "backend", "module_cache.pb")

	@staticmethod
	def invalidate_cache():
		"""
		Invalidate cache

		Practically this means just deleting the cache file, ensuring it will
		be regenerated
		"""
		try:
			os.unlink(ModuleCollector.get_cache_path())
		except FileNotFoundError:
			# cache not made yet, which is okay for our purposes
			pass