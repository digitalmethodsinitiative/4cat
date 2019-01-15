"""
General helper functions for Flask templating and 4CAT views
"""
import importlib
import datetime
import inspect
import json
import glob
import sys
import os
import re

from math import ceil
from fourcat import queue

from backend.abstract.postprocessor import BasicPostProcessor

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
					"description": member[1].description,
					"name": member[1].title,
					"extension": member[1].extension,
					"class": member[0]
				}

	return postprocessors


def get_available_postprocessors(query):
	"""
	Get available post-processors for a given query

	:param SearchQuery query:  Query to load available postprocessors for
	:return dict: Post processors, {id => settings} mapping
	"""
	postprocessors = load_postprocessors()
	available = postprocessors.copy()
	analyses = query.get_analyses(queue)

	for subquery in analyses["running"]:
		details = json.loads(subquery["parameters"])
		if "type" in details and details["type"] in available:
			del available[details["type"]]

	for job in analyses["queued"]:
		if job["jobtype"] in available:
			del available[job["jobtype"]]

	return available