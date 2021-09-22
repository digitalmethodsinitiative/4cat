"""
Miscellaneous helper functions for the 4CAT backend
"""
import subprocess
import datetime
import smtplib
import socket
import copy
import json
import csv
import re
import os

from pathlib import Path
from html.parser import HTMLParser
from werkzeug.datastructures import FileStorage
from calendar import monthrange

from common.lib.user_input import UserInput
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


def sniff_encoding(file):
	"""
	Determine encoding from raw file bytes

	Currently only distinguishes UTF-8 and UTF-8 with BOM

	:param FileStorage file:
	:return:
	"""
	if hasattr(file, "getbuffer"):
		buffer = file.getbuffer()
		maybe_bom = buffer[:3].tobytes()
	elif hasattr(file, "peek"):
		buffer = file.peek(32)
		maybe_bom = buffer[:3]
	else:
		maybe_bom = False

	return "utf-8-sig" if maybe_bom == b"\xef\xbb\xbf" else "utf-8"


def get_software_version():
	"""
	Get current 4CAT version

	Reads a given version file and returns the first string found in there
	(up until the first space). On failure, return an empty string.

	If no version file is available, run `git show` to test if there is a git
	repository in the 4CAT root folder, and if so, what commit is currently
	checked out in it.

	:return str:  4CAT version
	"""
	versionpath = Path(config.PATH_ROOT, config.PATH_VERSION)

	if versionpath.exists() and not versionpath.is_file():
		return ""

	if not versionpath.exists():
		# try github command line within the 4CAT root folder
		# if it is a checked-out git repository, it will tell us the hash of
		# the currently checked-out commit
		try:
			cwd = os.getcwd()
			os.chdir(config.PATH_ROOT)
			show = subprocess.run(["git", "show"], stderr=subprocess.PIPE, stdout=subprocess.PIPE)
			os.chdir(cwd)
			if show.returncode != 0:
				raise ValueError()
			return show.stdout.decode("utf-8").split("\n")[0].split(" ")[1]
		except (subprocess.SubprocessError, IndexError, TypeError, ValueError, FileNotFoundError):
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


def expand_short_number(text):
	"""
	Expands a number descriptor like '300K' to an integer like '300000'

	Wil raise a ValueError if the number cannot be converted

	:param text: Number descriptor
	:return int:  Number
	"""
	try:
		return int(text)
	except ValueError:
		number_bit = float(re.split(r"[^0-9.]", text)[0])
		multiplier_bit = re.sub(r"[0-9.]", "", text).strip()
		if multiplier_bit == "K":
			return int(number_bit * 1000)
		elif multiplier_bit == "M":
			return int(number_bit * 1000000)
		else:
			raise ValueError("Unknown multiplier '%s' in number '%s'" % (multiplier_bit, text))


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


def get_4cat_canvas(path, width, height, header=None, footer="made with 4CAT", fontsize_normal=None,
					fontsize_small=None, fontsize_large=None):
	"""
	Get a standard SVG canvas to draw 4CAT graphs to

	Adds a border, footer, header, and some basic text styling

	:param path:  The path where the SVG graph will be saved
	:param width:  Width of the canvas
	:param height:  Height of the canvas
	:param header:  Header, if necessary to draw
	:param footer:  Footer text, if necessary to draw. Defaults to shameless
	4CAT advertisement.
	:param fontsize_normal:  Font size of normal text
	:param fontsize_small:  Font size of small text (e.g. footer)
	:param fontsize_large:  Font size of large text (e.g. header)
	:return SVG:  SVG canvas (via svgwrite) that can be drawn to
	"""
	from svgwrite.container import SVG
	from svgwrite.drawing import Drawing
	from svgwrite.shapes import Rect
	from svgwrite.text import Text

	if fontsize_normal is None:
		fontsize_normal = width / 75

	if fontsize_small is None:
		fontsize_small = width / 100

	if fontsize_large is None:
		fontsize_large = width / 50

	# instantiate with border and white background
	canvas = Drawing(str(path), size=(width, height), style="font-family:monospace;font-size:%ipx" % fontsize_normal)
	canvas.add(Rect(insert=(0, 0), size=(width, height), stroke="#000", stroke_width=2, fill="#FFF"))

	# header
	if header:
		header_shape = SVG(insert=(0, 0), size=("100%", fontsize_large * 2))
		header_shape.add(Rect(insert=(0, 0), size=("100%", "100%"), fill="#000"))
		header_shape.add(
			Text(insert=("50%", "50%"), text=header, dominant_baseline="middle", text_anchor="middle", fill="#FFF",
				 style="font-size:%ipx" % fontsize_large))
		canvas.add(header_shape)

	# footer (i.e. 4cat banner)
	if footer:
		footersize = (fontsize_small * len(footer) * 0.7, fontsize_small * 2)
		footer_shape = SVG(insert=(width - footersize[0], height - footersize[1]), size=footersize)
		footer_shape.add(Rect(insert=(0, 0), size=("100%", "100%"), fill="#000"))
		footer_shape.add(
			Text(insert=("50%", "50%"), text=footer, dominant_baseline="middle", text_anchor="middle", fill="#FFF",
				 style="font-size:%ipx" % fontsize_small))
		canvas.add(footer_shape)

	return canvas


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
	connection.connect((config.API_HOST, config.API_PORT))

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


def get_interval_descriptor(item, interval):
	"""
	Get interval descriptor based on timestamp

	:param dict item:  Item to generate descriptor for, should have a
	"timestamp" key
	:param str interval:  Interval, one of "all", "overall", "year",
	"month", "week", "day"
	:return str:  Interval descriptor, e.g. "overall", "2020", "2020-08",
	"2020-43", "2020-08-01"
	"""
	if interval in ("all", "overall"):
		return interval

	if "timestamp" not in item:
		return "invalid_date"

	# Catch cases where a custom timestamp has an epoch integer as value.
	try:
		timestamp = int(item["timestamp"])
		try:
			timestamp = datetime.datetime.fromtimestamp(timestamp)
		except (ValueError, TypeError) as e:
			return "invalid_date"
	except:
		try:
			timestamp = datetime.datetime.strptime(item["timestamp"], "%Y-%m-%d %H:%M:%S")
		except (ValueError, TypeError) as e:
			return "invalid_date"

	if interval == "year":
		return str(timestamp.year)
	elif interval == "month":
		return str(timestamp.year) + "-" + str(timestamp.month).zfill(2)
	elif interval == "week":
		return str(timestamp.isocalendar()[0]) + "-" + str(timestamp.isocalendar()[1]).zfill(2)
	else:
		return str(timestamp.year) + "-" + str(timestamp.month).zfill(2) + "-" + str(timestamp.day).zfill(2)


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


def is_rankable(dataset):
	"""
	Determine if a dataset is rankable

	:todo:  Should this be part of the DataSet class?

	:param DataSet dataset:  Dataset to inspect
	:return bool:  Whether the dataset is rankable or not
	"""
	if dataset.get_results_path().suffix != ".csv":
		return False

	with dataset.get_results_path().open(encoding="utf-8") as infile:
		reader = csv.DictReader(infile)
		return len(set(reader.fieldnames) & {"date", "value", "item", "word_1"}) >= 3


def gdf_escape(string):
	"""
	Escape string for usage in GDF file

	:param str string:  String to escape
	:return str:  Escaped string
	"""
	return "'" + string.replace("'", "\\'").replace("\n", "\\n") + "'"


def dict_search_and_update(item, keyword_matches, function):
	"""
	Apply a function to every item and sub item of a dictionary if the key contains one of the provided match terms.

	Function loops through a dictionary or list and compares dictionary keys to the strings defined by keyword_matches.
	It then applies the change_function to corresponding values.

	Note: if a matching term is found, all nested values will have the function applied to them. e.g.,
	all these values would be changed even those with not_key_match:
	{'key_match' : 'changed',
	'also_key_match' : {'not_key_match' : 'but_value_still_changed'},
	'another_key_match': ['this_is_changed', 'and_this', {'not_key_match' : 'even_this_is_changed'}]}

	This is a comprehensive (and expensive) approach to updating a dictionary.
	IF a dictionary structure is known, a better solution would be to update using specific keys.

	:param Dict/List item:  dictionary/list/json to loop through
	:param String keyword_matches:  list of strings that will be matched to dictionary keys
	:param Function function:  function appled to all values of any items nested under a matching key
	:return Dict/List: Copy of original item
	"""
	def loop_helper_function(d_or_l, match_terms, change_function):
		"""
		Recursive helper function that updates item in place
		"""
		if isinstance(d_or_l, dict):
			# Iterate through dictionary
			for key, value in iter(d_or_l.items()):
				if match_terms == 'True' or any([match in key.lower() for match in match_terms]):
					# Match found; apply function to all items and sub-items
					if isinstance(value, (list, dict)):
						# Pass item through again with match_terms = True
						loop_helper_function(value, 'True', change_function)
					elif value is None:
						pass
					else:
						# Update the value
						d_or_l[key] = change_function(value)
				elif isinstance(value, (list, dict)):
					# Continue search
					loop_helper_function(value, match_terms, change_function)
		elif isinstance(d_or_l, list):
			# Iterate through list
			for n, value in enumerate(d_or_l):
				if isinstance(value, (list, dict)):
					# Continue search
					loop_helper_function(value, match_terms, change_function)
				elif match_terms == 'True':
					# List item nested in matching
					d_or_l[n] = change_function(value)
		else:
			raise Exception('Must pass list or dictionary')

	# Lowercase keyword_matches
	keyword_matches = [keyword.lower() for keyword in keyword_matches]

	# Create deepcopy and return new item
	temp_item = copy.deepcopy(item)
	loop_helper_function(temp_item, keyword_matches, function)
	return temp_item


def send_email(recipient, message):
	"""
	Send an e-mail using the configured SMTP settings

	Just a thin wrapper around smtplib, so we don't have to repeat ourselves.
	Exceptions are to be handled outside the function.

	:param list recipient:  Recipient e-mail addresses
	:param MIMEMultipart message:  Message to send
	"""
	connector = smtplib.SMTP_SSL if hasattr(config, "MAIL_SSL") and config.MAIL_SSL else smtplib.SMTP

	with connector(config.MAILHOST) as smtp:
		if hasattr(config, "MAIL_USERNAME") and hasattr(config, "MAIL_PASSWORD") and config.MAIL_USERNAME and config.MAIL_PASSWORD:
			smtp.ehlo()
			smtp.login(config.MAIL_USERNAME, config.MAIL_PASSWORD)

		smtp.sendmail(config.NOREPLY_EMAIL, recipient, message.as_string())