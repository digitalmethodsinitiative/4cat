"""
Miscellaneous helper functions for the 4CAT backend
"""
import collections
import importlib
import inspect
import glob
import sys
import csv
import os
import re

from html.parser import HTMLParser

import config


def posts_to_csv(sql_results, filepath, clean_csv=True):
	"""
	Takes a dictionary of results, converts it to a csv, and writes it to the data folder.
	The respective csvs will be available to the user.

	:param sql_results:		List with results derived with db.fetchall()
	:param filepath:    	Filepath for the resulting csv
	:param clean_csv:   	Whether to parse the raw HTML data to clean text.
							If True (default), writing takes 1.5 times longer.

	"""
	if not filepath:
		raise Exception("No result file for query")

	fieldnames = list(sql_results[0].keys())
	fieldnames.append("unix_timestamp")

	# write the dictionary to a csv
	with open(filepath, 'w', encoding='utf-8') as csvfile:
		writer = csv.DictWriter(csvfile, fieldnames=fieldnames, lineterminator='\n')
		writer.writeheader()

		if clean_csv:
			# Parsing: remove the HTML tags, but keep the <br> as a newline
			# Takes around 1.5 times longer
			for row in sql_results:
				# Create human dates from timestamp
				from datetime import datetime
				if "timestamp" in row:
					row["unix_timestamp"] = row["timestamp"]
					row["timestamp"] = datetime.utcfromtimestamp(row["timestamp"]).strftime('%Y-%m-%d %H:%M:%S')
				else:
					row["timestamp"] = "undefined"
				# Parse html to text
				if row["body"]:
					row["body"] = strip_tags(row["body"])

				writer.writerow(row)
		else:
			writer.writerows(sql_results)

	return filepath


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
	if True or name not in config.DATASOURCES or "boards" not in config.DATASOURCES[name]:
		return

	for board in config.DATASOURCES[name]["boards"]:
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
					"file": file,
					"description": member[1].description,
					"name": member[1].title,
					"extension": member[1].extension,
					"category": member[1].category if hasattr(member[1], "category") else "other",
					"accepts": member[1].accepts if hasattr(member[1], "accepts") else [],
					"options": member[1].options if hasattr(member[1], "options") else {},
					"datasources": member[1].datasources if hasattr(member[1], "datasources") else []
				}

	sorted_postprocessors = collections.OrderedDict()
	for key in sorted(postprocessors, key=lambda postprocessor: postprocessors[postprocessor]["category"] +
																postprocessors[postprocessor]["name"].lower()):
		sorted_postprocessors[key] = postprocessors[key]

	backup = sorted_postprocessors.copy()
	for type in sorted_postprocessors:
		sorted_postprocessors[type]["further"] = []
		for possible_child in backup:
			if type in backup[possible_child]["accepts"]:
				sorted_postprocessors[type]["further"].append(possible_child)
	return sorted_postprocessors


class HTMLStripper(HTMLParser):
	def __init__(self):
		super().__init__()
		self.reset()
		self.strict = False
		self.convert_charrefs = True
		self.fed = []

	def handle_data(self, data):
		self.fed.append(data)

	def get_data(self):
		return ''.join(self.fed)


def strip_tags(html, convert_newlines=True):
	"""
	Strip HTML from a string

	:param html: HTML to strip
	:param convert_newlines: Convert <br> and </p> tags to \n before stripping
	:return: Stripped HTML
	"""
	if not html:
		return ""

	deduplicate_newlines = re.compile(r"\n+")

	if convert_newlines:
		html = html.replace("<br>", "\n").replace("</p>", "</p>\n")
		html = deduplicate_newlines.sub("\n", html)

	stripper = HTMLStripper()
	stripper.feed(html)
	return stripper.get_data()


def get_software_version():
	"""
	Get current 4CAT version

	Reads a given version file and returns the first string found in there
	(up until the first space). On failure, return an empty string.

	:return str:  4CAT version
	"""
	versionpath = config.PATH_ROOT + "/" + config.PATH_VERSION

	if not os.path.exists(versionpath) or not os.path.isfile(versionpath):
		return ""

	try:
		with open(versionpath, "r") as versionfile:
			version = versionfile.readline().split(" ")[0]
			return version
	except OSError:
		return ""


def get_lib_url(file):
	"""
	Returns the full URL of a library file on the 4CAT server.
	Useful when debugging as it works with localhost
	
	:param str file: The library file to return URL from (e.g. `raphael.js`)
	:return str: The absolute URL to return
	"""

	if file.endswith(".js"):
		ext = "js/"
	elif file.endswith(".css"):
		ext = "css/"
	else:
		return "Provide a filename with a valid extention (`.js` or `.css`)"

	if config.FlaskConfig.SERVER_NAME == "localhost:5000":
		url = "http://localhost/fourcat/webtool/static/" + ext + file
	else:
		url = "https://" + config.FlaskConfig.SERVER_NAME + "/static/" + ext + file

	return url


def convert_to_int(value, default=0):
	"""
	Convert a value to an integer, with a fallback

	The fallback is used if a TypeError is thrown during converstion to int.

	:param value:  Value to convert
	:param int default:  Default value, if conversion not possible
	:return int:  Converted value
	"""
	try:
		return int(value)
	except TypeError:
		return default


class UserInput:
	"""
	Class for handling user input

	Particularly for post-processors, it is important that user input is within
	parameters set by the post-processor, or post-processor behaviour may be
	undefined. This class offers a set of pre-defined form elements that can
	easily be parsed.
	"""
	OPTION_TOGGLE = "toggle"  # boolean toggle (checkbox)
	OPTION_CHOICE = "choice"  # one choice out of a list (select)
	OPTION_TEXT = "string"  # simple string or integer (input text)
	OPTION_MULTI = "multi"  # multiple values out of a list (select multiple)

	def parse(settings, choice):
		"""
		Filter user input

		Makes sure user input for post-processors is valid and within the
		parameters specified by the post-processor

		:param obj settings:  Settings, including defaults and valid options
		:param choice:  The chosen option, to be parsed
		:return:  Validated and parsed input
		"""
		type = settings.get("type", "")
		if type == UserInput.OPTION_TOGGLE:
			# simple boolean toggle
			return choice is not None
		elif type == UserInput.OPTION_MULTI:
			# any number of values out of a list of possible values
			# comma-separated during input, returned as a list of valid options
			chosen = choice.split(",")
			return [item for item in chosen if item in settings.get("options", [])]
		elif type == UserInput.OPTION_CHOICE:
			# select box
			# one out of multiple options
			# return option if valid, or default
			return choice if choice in settings.get("options", []) else settings.get("default", "")
		elif type == UserInput.OPTION_TEXT:
			# text string
			# optionally clamp it as an integer; return default if not a valid
			# integer
			if "max" in settings:
				try:
					choice = min(settings["max"], int(choice))
				except (ValueError, TypeError) as e:
					choice = settings.get("default")

			if "min" in settings:
				try:
					choice = max(settings["min"], int(choice))
				except (ValueError, TypeError) as e:
					choice = settings.get("default")

			return choice or settings.get("default")
		else:
			# no filtering
			return choice
