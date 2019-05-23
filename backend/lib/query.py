import collections
import hashlib
import random
import typing
import json
import time
import re
import os
from csv import DictWriter

import config
from backend.lib.job import Job, JobNotFoundException
from backend.lib.helpers import load_postprocessors, get_absolute_folder


class DataSet:
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

	subqueries = []
	postprocessors = {}
	genealogy = []

	def __init__(self, parameters={}, key=None, job=None, data=None, db=None, parent=None, extension="csv",
				 type="search"):
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
				raise TypeError("DataSet() requires a valid query key for its 'key' argument, \"%s\" given" % key)

			self.query = current["query"]
		elif job is not None:
			current = self.db.fetchone("SELECT * FROM queries WHERE parameters::json->>'job' = %s", (job,))
			if not current:
				raise TypeError("DataSet() requires a valid job ID for its 'job' argument")

			self.query = current["query"]
			self.key = current["key"]
		elif data is not None:
			current = data
			if "query" not in data or "key" not in data or "parameters" not in data or "key_parent" not in data:
				raise ValueError("DataSet() requires a complete query record for its 'data' argument")

			self.query = current["query"]
			self.key = current["key"]
		else:
			if parameters is None:
				raise TypeError("DataSet() requires either 'key', or 'parameters' to be given")

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
				"is_finished": False,
				"num_rows": 0
			}
			self.parameters = parameters

			if parent:
				self.data["key_parent"] = parent

			self.db.insert("queries", data=self.data)
			self.reserve_result_file(parameters, extension)

		# retrieve analyses and post-processors that may be run for this query
		analyses = self.db.fetchall("SELECT * FROM queries WHERE key_parent = %s ORDER BY timestamp ASC", (self.key,))
		self.subqueries = [DataSet(data=analysis, db=self.db) for analysis in analyses]
		self.postprocessors = self.get_available_postprocessors()

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

	def delete(self):
		"""
		Delete the query, and all its subqueries

		Deletes both database records and result files. Note that manipulating
		a query object after it has been deleted is undefined behaviour.
		"""
		# first, recursively delete sub-queries
		sub_queries = self.db.fetchall("SELECT * FROM queries WHERE key_parent = %s", (self.key,))
		for sub_query in sub_queries:
			sub_query = DataSet(key=sub_query["key"], db=self.db)
			sub_query.delete()

		# delete from database
		self.db.execute("DELETE FROM queries WHERE key = %s", (self.key,))

		# delete from drive
		try:
			os.unlink(self.get_results_path())
		except FileNotFoundError:
			# already deleted, apparently
			pass

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
		elif "country_flag" in parameters and parameters["country_flag"] and parameters["country_flag"] != "all":
			return "Flag: %s" % parameters["country_flag"]
		else:
			return default

	def reserve_result_file(self, parameters=None, extension="csv"):
		"""
		Generate a unique path to the results file for this query

		This generates a file name for the result of this query, and makes sure
		no file exists or will exist at that location other than the file we
		expect (i.e. the results file for this particular query).

		:param str extension: File extension, "csv" by default
		:param parameters:  Query parameters
		:return bool:  Whether the file path was successfully reserved
		"""
		if self.data["is_finished"]:
			raise RuntimeError("Cannot reserve results file for a finished query")

		# Use 'random' for random post queries
		if "random_amount" in parameters and parameters["random_amount"] > 0:
			file = 'random-' + str(parameters["random_amount"]) + '-' + self.data["key"]
		# Use country code for country flag queries
		elif "country_flag" in parameters and parameters["country_flag"] != 'all':
			file = 'countryflag-' + str(parameters["country_flag"]) + '-' + self.data["key"]
		# Use the querystring for string queries
		else:
			query_bit = self.data["query"].replace(" ", "-").lower()
			query_bit = re.sub(r"[^a-z0-9\-]", "", query_bit)
			file = query_bit + "-" + self.data["key"]
			file = re.sub(r"[-]+", "-", file)

		# Crop filename
		file = file[:250]

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
		# Return a unique key if random posts are queried
		if parameters.get("random_amount", None):
			random_int = str(random.randint(1, 10000000))
			return hashlib.md5(random_int.encode("utf-8")).hexdigest()

		# Return a hash based on parameters for other queries
		else:
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

	def update_version(self, version):
		"""
		Update software version used for this query

		This can be used to verify the code that was used to run this query.

		:param string version:  Version identifier
		:return bool:  Update successul?
		"""
		self.data["software_version"] = version
		updated = self.db.update("queries", where={"key": self.data["key"]}, data={"software_version": version})

		return updated > 0

	def get_version_url(self, file):
		"""
		Get a versioned github URL for the version this query was performed with

		:param file:  File to link within the repository
		:return:  URL, or an empty string
		"""
		if not self.data["software_version"] or not config.GITHUB_URL:
			return ""

		return config.GITHUB_URL + "/blob/" + self.data["software_version"] + "/" + file

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
		with open(self.get_results_path(), "w", encoding="utf-8") as results:
			writer = DictWriter(results, fieldnames=data[0].keys())
			writer.writeheader()

			for row in data:
				writer.writerow(row)

		self.update_status("Finished")
		self.finish(len(data))

	def top_key(self):
		"""
		Get key of root query

		Traverses the tree of queries this one is part of until it finds one
		with no parent query, then returns that query's key.

		Not to be confused with top kek.

		:return str: Parent key.
		"""
		genealogy = self.get_genealogy()
		return genealogy[0].key

	def get_genealogy(self):
		"""
		Get genealogy of this query

		Creates a list of DataSet objects, with the first one being the
		'top' query, and each subsequent one being a sub-query of the previous
		one, ending with the current query.

		:return list:  Query genealogy, oldest query first
		"""
		if self.genealogy or not self.key_parent:
			return self.genealogy

		key_parent = self.key_parent
		genealogy = []

		while True:
			try:
				parent = DataSet(key=key_parent, db=self.db)
			except TypeError:
				break

			genealogy.append(parent)
			if parent.key_parent:
				key_parent = parent.key_parent
			else:
				break

		genealogy.reverse()
		genealogy.append(self)
		self.genealogy = genealogy
		return self.genealogy

	def get_breadcrumbs(self):
		"""
		Get breadcrumbs navlink for use in permalinks

		Returns a string representing this query's genealogy that may be used
		to uniquely identify it.

		:return str: Nav link
		"""
		genealogy = self.get_genealogy()

		return ",".join([query.key for query in genealogy])

	def get_compatible_postprocessors(self):
		"""
		Get list of post-processors compatible with this query

		Checks whether this query type is one that is listed as being accepted
		by the post-processor, for each known type: if the post-processor does
		not specify accepted types (via the `accepts` attribute of the class),
		it is assumed it accepts 'search' queries as an input.

		:return dict:  Compatible post-processors, `name => properties` mapping
		"""
		postprocessors = load_postprocessors()

		available = collections.OrderedDict()
		for postprocessor in postprocessors.values():
			if (self.data["type"] == "search" and not postprocessor["accepts"] and (
					not postprocessor["datasources"] or self.parameters.get("datasource") in postprocessor["datasources"])) or \
					self.data["type"] in postprocessor["accepts"]:
				available[postprocessor["type"]] = postprocessor

		return available

	def get_available_postprocessors(self):
		"""
		Get list of post-processors that may be run for this query

		Returns all compatible postprocessors except for those that are already
		queued or finished and have no options. Postprocessors that have been
		run but have options are included so they may be run again with a
		different configuration

		:return dict:  Available post-processors, `name => properties` mapping
		"""
		postprocessors = self.get_compatible_postprocessors()

		for analysis in self.subqueries:
			if analysis.type not in postprocessors:
				continue

			if not postprocessors[analysis.type]["options"]:
				del postprocessors[analysis.type]

		return postprocessors

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
		"""
		Getter so we don't have to use .data all the time

		:param attr:  Data key to get
		:return:  Value
		"""
		if attr in self.data:
			return self.data[attr]
		else:
			print(self.data)
			raise KeyError("DataSet instance has no attribute %s" % attr)
