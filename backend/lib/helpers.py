"""
Miscellaneous helper functions for the 4CAT backend
"""
import socket
import json
import re

from pathlib import Path
from html.parser import HTMLParser
from calendar import monthrange

import config


def init_datasource(database, logger, queue, name):
	"""
	Initialize data source

	Queues jobs to scrape the boards that were configured to be scraped in the
	4CAT configuration file. If none were configured, nothing happens.

	:param Database database:  Database connection instance
	:param Logger logger:  Log handler
	:param JobQueue queue:  Job Queue instance
	:param string name:  ID of datasource that is being initialised
	"""
	pass


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
			if not choice:
				return []
			
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
	connection.settimeout(15)
	connection.connect(("localhost", config.API_PORT))

	msg = json.dumps({"request": action, "payload": payload})
	connection.sendall(msg.encode("ascii", "ignore"))

	try:
		response = ""
		while True:
			bytes = connection.recv(2048)
			if not bytes:
				break

			response += bytes.decode("ascii", "ignore")
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


def pad_interval(intervals, first_interval=None, last_interval=None):
	"""
	Pad an interval so all intermediate intervals are filled

	:param dict intervals:  A dictionary, with dates (YYYY{-MM}{-DD}) as keys
	and a numerical value.
	:param first_interval:
	:param last_interval:
	:return:
	"""
	missing = 0
	test_key = list(intervals.keys())[0]

	# first determine the boundaries of the interval
	# these may be passed as parameters, or they can be inferred from the
	# interval given

	if first_interval:
		first_interval = str(first_interval)
		first_year = int(first_interval[0:4])
		if len(first_interval) > 4:
			first_month = int(first_interval[5:7])
		if len(first_interval) > 7:
			first_day = int(first_interval[8:10])
	else:
		first_year = min([int(i[0:4]) for i in intervals])
		if len(test_key) > 4:
			first_month = min([int(i[5:7]) for i in intervals if int(i[0:4]) == first_year])
		if len(test_key) > 7:
			first_day = min(
				[int(i[8:10]) for i in intervals if int(i[0:4]) == first_year and int(i[5:7]) == first_month])
	if last_interval:
		last_interval = str(last_interval)
		last_year = int(last_interval[0:4])
		if len(last_interval) > 4:
			last_month = int(last_interval[5:7])
		if len(last_interval) > 7:
			last_day = int(last_interval[8:10])
	else:
		last_year = max([int(i[0:4]) for i in intervals])
		if len(test_key) > 4:
			last_month = max([int(i[5:7]) for i in intervals if int(i[0:4]) == last_year])
		if len(test_key) > 7:
			last_day = max(
				[int(i[8:10]) for i in intervals if int(i[0:4]) == last_year and int(i[5:7]) == last_month])

	if re.match(r"^[0-9]{4}$", test_key):
		# years are quite straightforward
		for year in range(first_year, last_year + 1):
			if str(year) not in intervals:
				intervals[str(year)] = 0
				missing += 1

	elif re.match(r"^[0-9]{4}-[0-9]{2}(-[0-9]{2})?", test_key):
		# more granular intervals require the following monstrosity to
		# ensure all intervals are available for every single graph
		has_day = re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}", test_key)

		for year in range(first_year, last_year + 1):
			start_month = first_month if year == first_year else 1
			end_month = last_month if year == last_year else 12

			for month in range(start_month, end_month + 1):
				key = str(year) + "-" + str(month).zfill(2)
				if not has_day:
					if key not in intervals:
						intervals[key] = 0
						missing += 1
				else:
					start_day = first_day if year == first_year and month == first_month else 1
					end_day = last_day if year == last_year and month == last_month else \
						monthrange(year, month)[1]

					for day in range(start_day, end_day + 1):
						day_key = key + "-" + str(day).zfill(2)
						if day_key not in intervals:
							intervals[day_key] = 0
							missing += 1

	# sort while we're at it
	intervals = {key: intervals[key] for key in sorted(intervals)}

	return missing, intervals