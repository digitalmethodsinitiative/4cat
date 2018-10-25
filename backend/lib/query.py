import hashlib
import json
import time
import re
import os

import config
from backend.lib.helpers import get_absolute_folder


class SearchQuery:
	"""
	Provide interface to safely register and run search queries
	"""
	db = None
	data = None
	folder = None

	def __init__(self, query=None, parameters=None, key=None, db=None):
		"""
		Create new query object

		If the query is not in the database yet, it is added.

		:param str query:  Search query
		:param parameters:  Parameters, e.g. date limits, et cetera
		:param db:  Database connection
		"""
		self.db = db
		self.folder = get_absolute_folder(config.PATH_DATA)

		if key is not None:
			self.key = key
			current = self.db.fetchone("SELECT * FROM queries WHERE key = %s", (self.key,))
			if not current:
				raise TypeError("SearchQuery() requires a valid query key for its 'key' argument")
		else:
			if query is None or parameters is None:
				raise TypeError("SearchQuery() requires either 'key', or 'parameters' and 'query' to be given")

			self.key = self.get_key(query, parameters)
			current = self.db.fetchone("SELECT * FROM queries WHERE key = %s AND query = %s", (self.key, query))

		if current:
			self.data = current
		else:
			self.data = {
				"key": self.key,
				"query": query,
				"parameters": json.dumps(parameters),
				"result_file": "",
				"timestamp": int(time.time()),
				"is_finished": False
			}
			self.db.insert("queries", data=self.data)
			self.reserve_result_file()

	def get_finished_results_path(self):
		"""
		Get path to results file

		Only returns a path if the query is finished. In other words, if this
		method returns a path, a file with the complete results for this query
		will exist at that location.

		:return: A path to the results file, or `None`
		"""
		if self.data["is_finished"] and self.data["result_file"] and os.path.isfile(
				self.folder + "/" + self.data["result_file"]):
			return self.folder + "/" + self.data["result_file"]
		# elif self.data["is_finished"] and self.data["empty"]:
		# 	return 'empty_file'
		else:
			return None

	def get_results_path(self):
		"""
		Get path to results file

		Always returns a path, that will at some point contain the query
		results, but may not do so yet. Use this to get the location to write
		generated results to.

		:return str:  A path to the results file
		"""
		return self.folder + "/" + self.data["result_file"]

	def finish(self):
		"""
		Declare the query finished
		"""
		if self.data["is_finished"]:
			raise RuntimeError("Cannot finish a finished query again")

		self.db.update("queries", where={"query": self.data["query"], "key": self.data["key"]},
					   data={"is_finished": True})
		self.data["is_finished"] = True

	def reserve_result_file(self, extension="csv"):
		"""
		Generate a unique path to the results file for this query

		This generates a file name for the result of this query, and makes sure
		no file exists or will exist at that location other than the file we
		expect (i.e. the results file for this particular query).

		:param str extension: File extension, "csv" by default
		:return bool:  Whether the file path was successfully reserved
		"""
		if self.data["is_finished"]:
			raise RuntimeError("Cannot reserve results file for a finished query")

		query_bit = self.data["query"].replace(" ", "_").lower()
		query_bit = re.sub(r"[^a-z0-9]", "", query_bit)
		file = query_bit + "-" + self.data["key"]

		path = self.folder + "/" + file + "." + extension.lower()
		index = 1
		while os.path.isfile(path):
			path = self.folder + "/" + file + "-" + str(index) + "." + extension.lower()
			index += 1

		file = path.split("/").pop()
		updated = self.db.update("queries", where={"query": self.data["query"], "key": self.data["key"]},
								 data={"result_file": file})
		self.data["result_file"] = file
		return updated > 0

	def get_key(self, query, parameters):
		"""
		Generate a unique key for this query that can be used to identify it

		The key is a hash of a combination of the query string and parameters.
		You never need to call this, really: it's used internally.

		:param str query:  Query string
		:param parameters:  Query parameters
		:return str:  Query key
		"""
		plain_key = repr(parameters) + query
		return hashlib.md5(plain_key.encode("utf-8")).hexdigest()
