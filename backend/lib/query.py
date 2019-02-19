import collections
import hashlib
import typing
import json
import time
import re
import os
from csv import DictWriter

import config
from backend.lib.job import Job, JobNotFoundException
from backend.lib.helpers import load_postprocessors, get_absolute_folder


class SearchQuery:
	"""
	Provide interface to safely register and run search queries

	The actual searching is done in string_query - this class is here to make
	sure the results end up in the right place and do not conflict with similar
	other queries.
	"""
	db = None
	data = None
	folder = None
	parameters = {}
	is_new = True

	def __init__(self, parameters={}, key=None, job=None, data=None, db=None, parent=None, extension="csv", type="search"):
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
			current = self.db.fetchone("SELECT * FROM queries WHERE parameters::json->>'job' = %s", (job,))
			if not current:
				raise TypeError("SearchQuery() requires a valid job ID for its 'job' argument")

			self.query = current["query"]
			self.key = current["key"]
		elif data is not None:
			current = data
			if "query" not in data or "key" not in data or "parameters" not in data or "key_parent" not in data:
				raise ValueError("SearchQuery() requires a complete query record for its 'data' argument")

			self.query = current["query"]
			self.key = current["key"]
		else:
			if parameters is None:
				raise TypeError("SearchQuery() requires either 'key', or 'parameters' to be given")

			self.query = self.get_label(parameters, default=type)
			self.key = self.get_key(self.query, parameters, parent)
			current = self.db.fetchone("SELECT * FROM queries WHERE key = %s AND query = %s", (self.key, self.query))

		if current:
			self.data = current
			self.parameters = json.loads(self.data["parameters"])
			self.is_new = False
		else:
			self.data = {
				"key": self.key,
				"query": self.get_label(parameters, default=type),
				"parameters": json.dumps(parameters),
				"result_file": "",
				"status": "",
				"type": type,
				"timestamp": int(time.time()),
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
		or 'empty_file' when there were not matches.

		Only returns a path if the query is finished. In other words, if this
		method returns a path, a file with the complete results for this query
		will exist at that location.

		If the keyword-dense thread data was queried, it returns a list
		of data and metadata

		:return: A path to the results file, 'empty_file', or `None`
		"""
		if self.data["is_finished"] and self.data["num_rows"] > 0:
			return self.folder + "/" + self.data["result_file"]
		elif self.data["is_finished"] and self.data["num_rows"] == 0:
			return 'empty'
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

	def get_label(self, parameters=None, default="Query"):
		if not parameters:
			parameters = self.parameters

		if "body_query" in parameters and parameters["body_query"] and parameters["body_query"] != "empty":
			return parameters["body_query"]
		elif "subject_query" in parameters and parameters["subject_query"] and parameters["subject_query"] != "empty":
			return parameters["subject_query"]
		else:
			return default

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
		file = re.sub(r"[-]+", "-", file)

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

	def get_key(self, query, parameters, parent=""):
		"""
		Generate a unique key for this query that can be used to identify it

		The key is a hash of a combination of the query string and parameters.
		You never need to call this, really: it's used internally.

		:param str query:  Query string
		:param parameters:  Query parameters
		:param parent: Parent query's key (if applicable)

		:return str:  Query key
		"""
		# we're going to use the hash of the parameters to uniquely identify
		# the query, so make sure it's always in the same order, or we might
		# end up creating multiple keys for the same query if python
		# decides to return the dict in a different order
		param_key = collections.OrderedDict()
		for key in sorted(parameters):
			param_key[key] = parameters[key]

		parent_key = str(parent) if parent else ""
		plain_key = repr(param_key) + str(query) + parent_key
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

	def get_analyses(self):
		"""
		Get analyses for this query

		:return dict: Dict with two lists: one `queued` (jobs) and one
		`running` (queries)
		"""
		results = []
		analyses_records = self.db.fetchall("SELECT * FROM queries WHERE key_parent = %s", (self.key,))
		analyses = [SearchQuery(data=analysis, db=self.db) for analysis in analyses_records]

		for analysis in analyses:
			postprocessors = analysis.get_compatible_postprocessors()

			analysis.data["_subqueries"] = analysis.get_analyses()
			analysis.data["_postprocessors"] = {key: value for key, value in postprocessors.items() if key not in [analysis.data["type"] for analysis in analyses]}

			results.append(analysis)

		return results

	def get_compatible_postprocessors(self):
		"""
		Get list of post-processors available for this query

		Checks whether this query type is one that is listed as being accepted
		by the post-processor, for each known type: if the post-processor does
		not specify accepted types (via the `accepts` attribute of the class),
		it is assumed it accepts 'search' queries as an input.

		:return dict:  Compatible post-processors, `name => properties` mapping
		"""
		postprocessors = load_postprocessors()

		available = {}
		for postprocessor in postprocessors.values():
			if (self.data["type"] == "search" and not postprocessor["accepts"]) or self.data["type"] in postprocessor["accepts"]:
				available[postprocessor["type"]] = postprocessor

		return available

	def link_job(self, job):
		"""
		Link this query to a job ID

		Updates the query data to include a reference to the job that will be
		executing (or has already executed) this job.

		Note that if no job can be found for this query, this method silently
		fails.

		:param Job job:  The job that will run this query

		:todo: If the job column ever gets used, make sure it always contains
		       a valid value, rather than silently failing this method.
		"""
		if type(job) != Job:
			raise TypeError("link_job requires a Job object as its argument")

		if "id" not in job.data:
			try:
				job = Job.get_by_remote_ID(self.key, self.db, jobtype=self.data["type"])
			except JobNotFoundException:
				return

		self.db.update("queries", where={"key": self.key}, data={"job": job.data["id"]})


	def __getattr__(self, attr):
		if attr in self.data:
			return self.data[attr]
		else:
			raise KeyError("SearchQuery instance has no attribute %s" % attr)