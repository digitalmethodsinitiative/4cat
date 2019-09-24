"""
Miscellaneous helper functions for the 4CAT backend
"""
import socket
import json
import ssl
import csv
import re

from pathlib import Path
from html.parser import HTMLParser

import config


def posts_to_csv(sql_results, filepath, clean_csv=True):
	"""
	Takes a dictionary of results, converts it to a csv, and writes it to the
	given location. This is mostly a generic dictionary-to-CSV processor but
	some specific processing is done on the "body" key to strip HTML from it,
	and a human-readable timestamp is provided next to the UNIX timestamp.

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
	if not isinstance(filepath, Path):
		filepath = Path(filepath)

	with filepath.open("w", encoding="utf-8") as csvfile:
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


def init_datasource(database, logger, queue, name):
	"""
	Initialize data source

	Queues jobs to scrape the boards that were configured to be scraped in the
	4CAT configuration file. If none were configured, nothing happens.

	:param database:
	:param logger:
	:param queue:
	:param name:
	"""
	if True or name not in config.DATASOURCES or "boards" not in config.DATASOURCES[name]:
		return

	for board in config.DATASOURCES[name]["boards"]:
		queue.add_job(name + "-board", remote_id=board, interval=60)


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
			return "".join(self.fed)

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
	versionpath = Path(config.PATH_ROOT, config.PATH_VERSION)

	if not versionpath.exists() or not versionpath.is_file():
		return ""

	try:
		with versionpath.open("r") as versionfile:
			version = versionfile.readline().split(" ")[0]
			return version
	except OSError:
		return ""


def convert_to_int(value, default=0):
	"""
	Convert a value to an integer, with a fallback

	The fallback is used if an Error is thrown during converstion to int.
	This is a convenience function, but beats putting try-catches everywhere
	we're using user input as an integer.

	:param value:  Value to convert
	:param int default:  Default value, if conversion not possible
	:return int:  Converted value
	"""
	try:
		return int(value)
	except (ValueError, TypeError):
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


def get_yt_compatible_ids(yt_ids):
	"""
	:param yt_ids list, a list of strings
	:returns list, a ist of joined strings in pairs of 50

	Takes a list of IDs and returns list of joined strings
	in pairs of fifty. This should be done for the YouTube API
	that requires a comma-separated string and can only return
	max fifty results.
	"""

	# If there's only one item, return a single list item 
	if isinstance(yt_ids, str):
		return [yt_ids]

	ids = []
	last_i = 0
	for i, yt_id in enumerate(yt_ids):

		# Add a joined string per fifty videos
		if i % 50 == 0 and i != 0:
			ids_string = ",".join(yt_ids[last_i:i])
			ids.append(ids_string)
			last_i = i

		# If the end of the list is reached, add the last data
		elif i == (len(yt_ids) - 1):
			ids_string = ",".join(yt_ids[last_i:i])
			ids.append(ids_string)

	return ids


def call_api(action, payload=None):
	"""
	Send message to server

	Calls the internal API and returns interpreted response.

	:param str action: API action
	:param payload: API payload

	:return: API response, or timeout message in case of timeout
	"""
	connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	connection.settimeout(5)
	connection.connect(("localhost", config.API_PORT))

	msg = json.dumps({"request": action, "payload": payload})
	connection.sendall(msg.encode("ascii", "ignore"))

	try:
		response = connection.recv(2048)
		response = response.decode("ascii", "ignore")
	except (socket.timeout, TimeoutError):
		response = "(Connection timed out)"

	try:
		connection.shutdown(socket.SHUT_RDWR)
	except OSError:
		# already shut down automatically
		pass
	connection.close()

	try:
		return json.loads(response)
	except json.JSONDecodeError:
		return response