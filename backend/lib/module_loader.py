"""
Load modules and datasources dynamically
"""
from pathlib import Path
import importlib
import inspect
import config
import sys

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
		self.load_datasources()
		self.load_modules()

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

		for folder in paths:
			# loop through folders, and files in those folders, recursively
			for file in folder.rglob("*.py"):
				# determine module name for file
				# reduce path to be relative to 4CAT root
				module_name = file.parts[:-1]
				for part in Path(config.PATH_ROOT).parts:
					module_name = module_name[1:]

				module_name = ".".join(list(module_name) + [file.stem])

				# check if we've already loaded this module
				if module_name in sys.modules or module_name in self.ignore:
					continue

				# try importing
				try:
					module = importlib.import_module(module_name)
				except ImportError as e:
					self.ignore.append(module_name)
					# this is fine, just ignore this
					continue

				# see if module contains the right type of content by looping
				# through all of its members
				components = inspect.getmembers(module)
				for component in components:
					# check if found object qualifies as a worker class
					is_4cat_module = False

					if component[0][0:2] != "__" \
							and inspect.isclass(component[1]) \
							and (issubclass(component[1], BasicWorker) or issubclass(component[1], BasicProcessor)) \
							and not inspect.isabstract(component[1]):
						is_4cat_module = True

					# nope? ignore it in the future
					if not is_4cat_module:
						continue

					# extract data that is useful for the scheduler and other
					# parts of 4CAT
					metadata = {
						"file": file.name,
						"id": component[1].type,
						"name": component[0],
						"max": component[1].max_workers,
						"class": component[1],
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
							"further": []
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

	def load_datasources(self):
		"""
		Load datasources

		This looks for folders within the datasource root folder that contain
		an `__init__.py` defining an `init_datasource` function and a
		`DATASOURCE` constant. The latter is taken as the ID for this
		datasource.
		"""
		for subdirectory in Path(config.PATH_ROOT, "datasources").iterdir():
			# determine module name
			module_name = "datasources." + subdirectory.parts[-1]
			try:
				datasource = importlib.import_module(module_name)
			except ImportError:
				continue

			if not hasattr(datasource, "init_datasource") or not hasattr(datasource, "DATASOURCE"):
				continue

			datasource_id = datasource.DATASOURCE
			self.datasources[datasource_id] = {
				"path": subdirectory,
				"name": datasource.NAME if hasattr(datasource, "NAME") else datasource_id
			}

		sorted_datasources = {datasource_id: self.datasources[datasource_id] for datasource_id in sorted(self.datasources, key=lambda id: self.datasources[id]["name"])}
		self.datasources = sorted_datasources