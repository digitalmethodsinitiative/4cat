"""
Miscellaneous helper functions for the 4CAT backend
"""
import collections
import importlib
import inspect
import glob
import sys
import os

import config


def get_absolute_folder(folder=""):
	"""
	Get absolute path to a folder

	Determines the absolute path of a given folder, which may be a relative
	or absolute path. Note that it is not checked whether the folder actually exists

	:return string:  Absolute folder path (no trailing slash)
	"""

	if len(folder) == 0 or folder[0] != os.sep:
		path = os.path.dirname(os.path.dirname(os.path.dirname(__file__))) + "/"  # 4cat root folder
		path += folder
	else:
		path = folder

	path = path[:-1] if len(path) > 0 and path[-1] == os.sep else path

	return path


def init_datasource(database, logger, queue, name):
	"""
	Initialize data source

	Queues jobs to scrape the boards that were
	:param database:
	:param logger:
	:param queue:
	:param name:
	:return:
	"""
	if name not in config.PLATFORMS or "boards" not in config.PLATFORMS[name]:
		return

	for board in config.PLATFORMS[name]["boards"]:
		queue.add_job(name + "-board", remote_id=board, interval=60)


def load_postprocessors():
	"""
	See what post-processors are available

	Looks for python files in the PP folder, then looks for classes that
	are a subclass of BasicPostProcessor that are available in those files, and
	not an abstract class themselves. Classes that meet those criteria are
	added to a list of available types.
	"""
	pp_folder = os.path.abspath(os.path.dirname(__file__)) + "/../../backend/postprocessors"
	os.chdir(pp_folder)
	postprocessors = {}

	# check for worker files
	for file in glob.glob("*.py"):
		module = "backend.postprocessors." + file[:-3]
		if module not in sys.modules:
			importlib.import_module(module)

		members = inspect.getmembers(sys.modules[module])

		for member in members:
			if inspect.isclass(member[1]) and "BasicPostProcessor" in [parent.__name__ for parent in
																	   member[1].__bases__] and not inspect.isabstract(
					member[1]):
				postprocessors[member[1].type] = {
					"type": member[1].type,
					"description": member[1].description,
					"name": member[1].title,
					"extension": member[1].extension,
					"class": member[0],
					"category": member[1].category if hasattr(member[1], "category") else "other",
					"accepts": member[1].accepts if hasattr(member[1], "accepts") else [],
					"options": member[1].options if hasattr(member[1], "options") else {}
				}

	sorted_postprocessors = collections.OrderedDict()
	for key in sorted(postprocessors, key=lambda postprocessor: postprocessors[postprocessor]["category"] + postprocessors[postprocessor]["name"].lower()):
		sorted_postprocessors[key] = postprocessors[key]

	return sorted_postprocessors


class UserInput:
	OPTION_TOGGLE = "toggle"
	OPTION_CHOICE = "choice"
	OPTION_TEXT = "string"

	def parse(settings, choice):
		type = settings.get("type", "")
		if type == UserInput.OPTION_TOGGLE:
			return choice is not None
		elif type == UserInput.OPTION_CHOICE:
			return choice if choice in settings.get("options", []) else settings.get("default", "")
		elif type == UserInput.OPTION_TEXT:
			print("Input: %s" % choice)
			if "max" in settings:
				try:
					choice = min(settings["max"], int(choice))
				except TypeError as e:
					choice = settings.get("default")

			if "min" in settings:
				try:
					choice = max(settings["min"], int(choice))
				except TypeError as e:
					choice = settings.get("default")

			return choice or settings.get("default")
		else:
			return choice
