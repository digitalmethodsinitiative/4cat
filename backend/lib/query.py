import hashlib
import typing
import json
import time
import re
import os
from csv import DictWriter

import config
from backend.lib.helpers import get_absolute_folder
from backend.lib.queue import JobQueue


class SearchQuery:
	"""
	Provide interface to safely register and run search queries
	"""
	db = None
	data = None
	folder = None
	parameters = None

	def __init__(self, parameters=None, key=None, job=None, db=None, parent=None, extension="csv"):
		"""
		Create new query object

		If the query is not in the database yet, it is added.

		:param parameters:  Parameters, e.g. string query, date limits, et cetera
		:param db:  Database connection
		"""
		self.db = db
		self.folder = get_absolute_folder(config.PATH_DATA)

		if key is not None:
			self.key = key
			current = self.db.fetchone("SELECT * FROM queries WHERE key = %s", (self.key,))
			if not current:
				raise TypeError("SearchQuery() requires a valid query key for its 'key' argument")

			self.query = current["query"]
		elif job is not None:
			current = self.db.fetchone("SELECT * FROM queries WHERE parameters::json->>job = %s", (job,))
			if not current:
				raise TypeError("SearchQuery() requires a valid job ID for its 'job' argument")

			self.query = current["query"]
			self.key = current["key"]
		else:
			if parameters is None:
				raise TypeError("SearchQuery() requires either 'key', or 'parameters' to be given")

			self.query = self.get_label(parameters)
			self.key = self.get_key(self.query, parameters)
			current = self.db.fetchone("SELECT * FROM queries WHERE key = %s AND query = %s", (self.key, self.query))

		if current:
			self.data = current
			self.parameters = json.loads(self.data["parameters"])
		else:
			self.data = {
				"key": self.key,
				"query": self.get_label(parameters),
				"parameters": json.dumps(parameters),
				"result_file": "",
				"status": "",
				"timestamp": int(time.time()),
				"is_empty": False,
				"is_finished": False
			}
			self.parameters = parameters

			if parent:
				self.data["key_parent"] = parent

			self.db.insert("queries", data=self.data)
			self.reserve_result_file(extension)

	def check_query_finished(self):
		"""
		Checks if query is finished. Returns path to results file is not empty,
		or 'empty_file' when ther were not matches.

		Only returns a path if the query is finished. In other words, if this
		method returns a path, a file with the complete results for this query
		will exist at that location.

		If the keyword-dense thread data was queried, it returns a list
		of data and metadata

		:return: A path to the results file, 'empty_file', or `None`
		"""
		if self.data["is_finished"] and self.data["result_file"] and os.path.isfile(
				self.folder + "/" + self.data["result_file"]):
			return self.folder + "/" + self.data["result_file"]
		elif self.data["is_finished"] and self.data["is_empty"]:
			return 'empty_file'
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

	def get_results_dir(self):
		"""
		Get path to results directory

		Always returns a path, that will at some point contain the query
		results, but may not do so yet. Use this to get the location to write
		generated results to.

		:return str:  A path to the results directory
		"""
		return self.folder

	def finish(self, num_rows=0):
		"""
		Declare the query finished
		"""
		if self.data["is_finished"]:
			raise RuntimeError("Cannot finish a finished query again")

		self.db.update("queries", where={"query": self.data["query"], "key": self.data["key"]},
					   data={"is_finished": True, "num_rows": num_rows})
		self.data["is_finished"] = True
		self.data["num_rows"] = num_rows

	def is_finished(self):
		"""
		Check if query is finished
		:return bool:
		"""
		return self.data["is_finished"] is True

	def get_parameters(self):
		"""
		Get query parameters

		The query parameters are stored as JSON in the database - parse them
		and return the resulting object

		:return:  Query parameters as originall stored
		"""
		try:
			return json.loads(self.data["parameters"])
		except json.JSONDecodeError:
			return {}

	def get_label(self, parameters=None):
		if not parameters:
			parameters = self.parameters

		if "body_query" in parameters and parameters["body_query"] and parameters["body_query"] != "empty":
			return parameters["body_query"]
		elif "subject_query" in parameters and parameters["subject_query"] and parameters["subject_query"] != "empty":
			return parameters["subject_query"]
		else:
			return "query"

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

		query_bit = self.data["query"].replace(" ", "-").lower()
		query_bit = re.sub(r"[^a-z0-9\-]", "", query_bit)
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
		plain_key = repr(parameters) + str(query)
		return hashlib.md5(plain_key.encode("utf-8")).hexdigest()

	def get_status(self):
		"""
		Get query status

		:return string: Query status
		"""
		return self.data["status"]

	def update_status(self, status):
		"""
		Update query status

		The status is a string that may be displayed to a user to keep them
		updated and informed about the progress of a query. No memory is kept
		of earlier query statuses; the current status is overwritten when
		updated.

		:param string status:  Query status
		:return bool:  Status update successful?
		"""
		self.data["status"] = status
		updated = self.db.update("queries", where={"key": self.data["key"]}, data={"status": status})

		return updated > 0

	def write_csv_and_finish(self, data):
		"""
		Write data as csv to results file and finish query

		Determines result file path using query's path determination helper
		methods. After writing results, the query is marked finished.

		:param data: A list or tuple of dictionaries, all with the same keys
		"""
		if not (isinstance(data, typing.List) or isinstance(data, typing.Tuple)) or isinstance(data, str):
			raise TypeError("write_as_csv requires a list or tuple of dictionaries as argument")

		if not data:
			raise ValueError("write_as_csv requires a dictionary with at least one item")

		if not isinstance(data[0], dict):
			raise TypeError("write_as_csv requires a list or tuple of dictionaries as argument")

		self.update_status("Writing results file")
		with open(self.get_results_path(), "w") as results:
			writer = DictWriter(results, fieldnames=data[0].keys())
			writer.writeheader()

			for row in data:
				writer.writerow(row)

		self.update_status("Finished")
		self.finish(len(data))

	def get_analyses(self, queue=False):
		"""
		Get analyses for this query

		:param queue:  If a JobQueue is passed as this parameter, queued
		post-processor jobs will also be fetched and included in the result
		:return dict: Dict with two lists: one `queued` (jobs) and one
		`running` (queries)
		"""
		results = {"queued": [], "running": []}

		results["running"] = self.db.fetchall("SELECT * FROM queries WHERE key_parent = %s", (self.key,))
		if queue:
			results["queued"] = queue.get_all_jobs(remote_id=self.key)

		return results

	def set_empty(self):
		"""
		Update the is_empty field of query in the database to indicate there
		are no substring matches.

		Should be tweaked to set is_empty to False if query was made sooner
		than n days ago to prevent false empty results.

		"""

		self.db.update("queries", where={"query": self.data["query"], "key": self.data["key"]},
								 data={"is_empty": True})