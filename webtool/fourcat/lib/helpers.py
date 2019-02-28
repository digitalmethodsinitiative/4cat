"""
General helper functions for Flask templating and 4CAT views
"""
import importlib
import datetime
import inspect
import glob
import sys
import os
import re
import csv

from math import ceil

from backend.abstract.postprocessor import BasicPostProcessor

from stop_words import get_stop_words


class Pagination(object):
	"""
	Provide pagination
	"""

	def __init__(self, page, per_page, total_count):
		"""
		Set up pagination object

		:param int page:  Current page
		:param int per_page:  Items per page
		:param int total_count:  Total number of items
		"""
		self.page = page
		self.per_page = per_page
		self.total_count = total_count

	@property
	def pages(self):
		"""
		:return int:  Number of pages in view
		"""
		return int(ceil(self.total_count / float(self.per_page)))

	@property
	def has_prev(self):
		"""
		:return bool:  Is there a previous page?
		"""
		return self.page > 1

	@property
	def has_next(self):
		"""
		:return bool:  Is there a next page?
		"""
		return self.page < self.pages

	def iter_pages(self, left_edge=2, left_current=2, right_current=5, right_edge=2):
		"""
		Page iterator

		Yields page numbers, or none if no further page is available

		:param left_edge:  Left edge of pages that may be returned
		:param left_current:  Current left edge
		:param right_current:  Current right edge
		:param right_edge:  Right edge of pages that may be returned
		:return:  A page number, or None
		"""
		last = 0
		for num in range(1, self.pages + 1):
			if num <= left_edge or \
					(num > self.page - left_current - 1 and \
					 num < self.page + right_current) or \
					num > self.pages - right_edge:
				if last + 1 != num:
					yield None
				yield num
				last = num


def string_to_timestamp(string):
	"""
	Convert dd-mm-yyyy date to unix time

	:param string: Date string to parse
	:return: The unix time, or 0 if value could not be parsed
	"""
	bits = string.split("-")
	if re.match(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", string):
		bits = list(reversed(bits))

	if len(bits) != 3:
		return 0

	try:
		day = int(bits[0])
		month = int(bits[1])
		year = int(bits[2])
		date = datetime.datetime(year, month, day)
	except ValueError:
		return 0

	return int(date.timestamp())


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
			if inspect.isclass(member[1]) and issubclass(member[1], BasicPostProcessor) and not inspect.isabstract(
					member[1]):
				postprocessors[member[1].type] = {
					"type": member[1].type,
					"category": member[1].category,
					"description": member[1].description,
					"name": member[1].title,
					"extension": member[1].extension,
					"class": member[0],
					"options": member[1].options if hasattr(member[1], "options") else {}
				}

	return postprocessors


def get_available_postprocessors(query):
	"""
	Get available post-processors for a given query

	:param SearchQuery query:  Query to load available postprocessors for
	:return dict: Post processors, {id => settings} mapping
	"""
	postprocessors = query.get_compatible_postprocessors()
	available = postprocessors.copy()
	analyses = query.get_analyses()

	for subquery in analyses:
		type = subquery.type
		if type in available and not available[type].get("options", {}):
			del available[type]

	return available


def get_preview(query):
	"""
	Generate a data preview of 25 rows of a results csv
	
	:param query 
	:return list: 
	"""
	preview = []
	with open(query.get_results_path(), encoding="utf-8") as resultfile:
		posts = csv.DictReader(resultfile)
		i = 0
		for post in posts:
			i += 1
			post["body"] = format_post(post["body"])
			preview.append(post)
			if i > 25:
				break
	return preview


def format_post(post):
	"""
	Format a plain-text 4chan post for HTML display

	Converts >>references into links and adds a class to greentext.s

	:param str post:  Post body
	:return str:  Formatted post body
	"""
	post = post.replace(">", "&gt;")
	post = re.sub(r"&gt;&gt;([0-9]+)", "<span class=\"quote\"><a href=\"#post-\\1\">&gt;&gt;\\1</a></span>", post)
	post = re.sub(r"^&gt;([^\n]+)", "<span class=\"greentext\">&gt;\\1</span>", post, flags=re.MULTILINE)
	return post


def validate_query(parameters):
	"""
	Validate client-side input

	:param parameters:  Parameters to validate
	:return:
	"""

	if not parameters:
		return "Please provide valid parameters."

	stop_words = get_stop_words('en')

	# TEMPORARY MEASUREMENT
	# Querying can only happen for max two weeks
	# max_daterange = 1209600

	# if parameters["min_date"] == 0 or parameters["max_date"] == 0:
	# 	return "Temporary hardware limitation:\nUse a date range of max. two weeks."

	# Ensure querying can only happen for max two weeks week (temporary measurement)
	# if parameters["min_date"] != 0 and parameters["max_date"] != 0:
	# 	if (parameters["max_date"] - parameters["min_date"]) > max_daterange:
	# 		return "Temporary hardware limitation:\nUse a date range of max. two weeks."

	# Ensure no weird negative timestamps happening
	if parameters["min_date"] < 0 or parameters["max_date"] < 0:
		return "Date(s) set too early."

	# Ensure the min date is not later than the max date
	if parameters["min_date"] != 0 and parameters["max_date"] != 0:
		if parameters["min_date"] >= parameters["max_date"]:
			return "The first date is later than or the same as the second."

	# Ensure the board is correct
	if "platform" not in parameters or "board" not in parameters:
		return "Please provide a board to search"

	if parameters["platform"] not in config.PLATFORMS:
		return "Please choose a valid platform to search"

	if parameters["board"] not in config.PLATFORMS[parameters["platform"]]["boards"]:
		return "Please choose a valid board for querying"

	# Keyword-dense thread length should be at least thirty.
	if parameters["dense_length"] > 0 and parameters["dense_length"] < 10:
		return "Keyword-dense thread length should be at least ten."
	# Keyword-dense thread density should be at least 15%.
	elif parameters["dense_percentage"] > 0 and parameters["dense_percentage"] < 10:
		return "Keyword-dense thread density should be at least 10%."

	# Check if there are enough parameters provided.
	# Body and subject queryies may be empty if date ranges are max a week apart.
	if parameters["body_query"] == "" and parameters["subject_query"] == "":
		# Check if the date range is less than a week.
		if parameters["min_date"] != 0 and parameters["max_date"] != 0:
			time_diff = parameters["max_date"] - parameters["min_date"]
			if time_diff >= 2419200:
				return "With no text querying, filter on a date range of max four weeks."
			else:
				return True
		else:
			return "Input either a body or subject query, or filter on a date range of max four weeks."

	# Body query should be at least three characters long and should not be just a stopword.
	if parameters["body_query"] and len(parameters["body_query"]) < 3:
		return "Body query is too short. Use at least three characters."
	elif parameters["body_query"] in stop_words:
		return "Use a body input that is not a stop word."
	# Query must contain alphanumeric characters
	elif parameters["body_query"] and not re.search('[a-zA-Z0-9]', parameters["body_query"]):
		return "Body query must contain alphanumeric characters."

	# Subject query should be at least three characters long and should not be just a stopword.
	if parameters["subject_query"] and len(parameters["subject_query"]) < 3:
		return "Subject query is too short. Use at least three characters."
	elif parameters["subject_query"] in stop_words:
		return "Use a subject input that is not a stop word."
	elif parameters["subject_query"] and not re.search('[a-zA-Z0-9]', parameters["subject_query"]):
		# Query must contain alphanumeric characters
		return "Subject query must contain alphanumeric characters."

	return True

