import collections
import datetime
import hashlib
import random
import shutil
import json
import time
import csv
import re

from pathlib import Path

import config
import backend
from common.lib.job import Job, JobNotFoundException
from common.lib.helpers import get_software_version
from common.lib.fourcat_module import FourcatModule


class DataSet(FourcatModule):
	"""
	Provide interface to safely register and run operations on a dataset

	A dataset is a collection of:
	- A unique identifier
	- A set of parameters that demarcate the data contained within
	- The data

	The data is usually stored in a file on the disk; the parameters are stored
	in a database. The handling of the data, et cetera, is done by other
	workers; this class defines method to create and manipulate the dataset's
	properties.
	"""
	data = {}
	key = ""

	children = []
	available_processors = {}
	genealogy = []
	preset_parent = None
	parameters = {}

	db = None
	folder = None
	is_new = True
	no_status_updates = False

	def __init__(self, parameters={}, key=None, job=None, data=None, db=None, parent=None, extension="csv",
				 type=None):
		"""
		Create new dataset object

		If the dataset is not in the database yet, it is added.

		:param parameters:  Parameters, e.g. search query, date limits, et cetera
		:param db:  Database connection
		"""
		self.db = db
		self.folder = Path(config.PATH_ROOT, config.PATH_DATA)

		if key is not None:
			self.key = key
			current = self.db.fetchone("SELECT * FROM datasets WHERE key = %s", (self.key,))
			if not current:
				raise TypeError("DataSet() requires a valid dataset key for its 'key' argument, \"%s\" given" % key)

			query = current["query"]
		elif job is not None:
			current = self.db.fetchone("SELECT * FROM datasets WHERE parameters::json->>'job' = %s", (job,))
			if not current:
				raise TypeError("DataSet() requires a valid job ID for its 'job' argument")

			query = current["query"]
			self.key = current["key"]
		elif data is not None:
			current = data
			if "query" not in data or "key" not in data or "parameters" not in data or "key_parent" not in data:
				raise ValueError("DataSet() requires a complete dataset record for its 'data' argument")

			query = current["query"]
			self.key = current["key"]
		else:
			if parameters is None:
				raise TypeError("DataSet() requires either 'key', or 'parameters' to be given")

			if not type:
				raise ValueError("Datasets must have their type set explicitly")

			query = self.get_label(parameters, default=type)
			self.key = self.get_key(query, parameters, parent)
			current = self.db.fetchone("SELECT * FROM datasets WHERE key = %s AND query = %s", (self.key, query))

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
				"software_version": get_software_version(),
				"software_file": "",
				"num_rows": 0,
				"key_parent": parent
			}
			self.parameters = parameters

			self.db.insert("datasets", data=self.data)
			self.reserve_result_file(parameters, extension)

		# retrieve analyses and processors that may be run for this dataset
		analyses = self.db.fetchall("SELECT * FROM datasets WHERE key_parent = %s ORDER BY timestamp ASC", (self.key,))
		self.children = sorted([DataSet(data=analysis, db=self.db) for analysis in analyses],
							   key=lambda dataset: dataset.is_finished(), reverse=True)

	def check_dataset_finished(self):
		"""
		Checks if dataset is finished. Returns path to results file is not empty,
		or 'empty_file' when there were not matches.

		Only returns a path if the dataset is complete. In other words, if this
		method returns a path, a file with the complete results for this dataset
		will exist at that location.

		:return: A path to the results file, 'empty_file', or `None`
		"""
		if self.data["is_finished"] and self.data["num_rows"] > 0:
			return self.folder.joinpath(self.data["result_file"])
		elif self.data["is_finished"] and self.data["num_rows"] == 0:
			return 'empty'
		else:
			return None

	def get_results_path(self):
		"""
		Get path to results file

		Always returns a path, that will at some point contain the dataset
		data, but may not do so yet. Use this to get the location to write
		generated results to.

		:return Path:  A path to the results file
		"""
		return self.folder.joinpath(self.data["result_file"])

	def get_log_path(self):
		"""
		Get path to dataset log file

		Each dataset has a single log file that documents its creation. This
		method returns the path to that file. It is identical to the path of
		the dataset result file, with 'log' as its extension instead.

		:return Path:  A path to the log file
		"""
		return self.get_results_path().with_suffix(".log")

	def clear_log(self):
		"""
		Clears the dataset log file

		If the log file does not exist, it is created empty. The log file will
		have the same file name as the dataset result file, with the 'log'
		extension.
		"""
		log_path = self.get_log_path()
		with log_path.open("w") as outfile:
			pass

	def has_log_file(self):
		"""
		Check if a log file exists for this dataset

		This should be the case, but datasets created before status logging was
		added may not have one, so we need to be able to check this.

		:return bool:  Does a log file exist?
		"""
		return self.get_log_path().exists()

	def log(self, log):
		"""
		Write log message to file

		Writes the log message to the log file on a new line, including a
		timestamp at the start of the line. Note that this assumes the log file
		already exists - it should have been created/cleared with clear_log()
		prior to calling this.

		:param str log:  Log message to write
		"""
		log_path = self.get_log_path()
		with log_path.open("a", encoding="utf-8") as outfile:
			outfile.write("%s: %s\n" % (datetime.datetime.now().strftime("%c"), log))

	def get_log_iterator(self):
		"""
		Return an iterator with a (time, message) tuple per line in the log

		Just a convenience function!

		:return iterator:  (time, message) per log message
		"""
		log_path = self.get_log_path()
		if not log_path.exists():
			return

		with log_path.open(encoding="utf-8") as infile:
			for line in infile:
				logtime = line.split(":")[0]
				logmsg = ":".join(line.split(":")[1:])
				yield (logtime, logmsg)

	def get_staging_area(self):
		"""
		Get path to a temporary folder in which files can be stored before
		finishing

		This folder must be created before use, but is guaranteed to not exist
		yet. The folder may be used as a staging area for the dataset data
		while it is being processed.

		:return Path:  Path to folder
		"""
		results_file = self.get_results_path()

		results_dir_base = Path(results_file.parent)
		results_dir = results_file.name.replace(".", "") + "-staging"
		results_path = results_dir_base.joinpath(results_dir)
		index = 1
		while results_path.exists():
			results_path = results_dir_base.joinpath(results_dir + "-" + str(index))
			index += 1

		# create temporary folder
		results_path.mkdir()
		return results_path

	def get_results_dir(self):
		"""
		Get path to results directory

		Always returns a path, that will at some point contain the dataset
		data, but may not do so yet. Use this to get the location to write
		generated results to.

		:return str:  A path to the results directory
		"""
		return self.folder

	def finish(self, num_rows=0):
		"""
		Declare the dataset finished
		"""
		if self.data["is_finished"]:
			raise RuntimeError("Cannot finish a finished dataset again")

		self.db.update("datasets", where={"key": self.data["key"]},
					   data={"is_finished": True, "num_rows": num_rows})
		self.data["is_finished"] = True
		self.data["num_rows"] = num_rows

	def unfinish(self):
		"""
		Declare unfinished, and reset status, so that it may be executed again.
		"""
		if not self.is_finished():
			raise RuntimeError("Cannot unfinish an unfinished dataset")

		try:
			self.get_results_path().unlink()
		except FileNotFoundError:
			pass

		self.data["timestamp"] = int(time.time())
		self.data["is_finished"] = False
		self.data["num_rows"] = 0
		self.data["status"] = "Dataset is queued."

		self.db.update("datasets", data={
			"timestamp": self.data["timestamp"],
			"is_finished": self.data["is_finished"],
			"num_rows": self.data["num_rows"],
			"status": self.data["status"]
		}, where={"key": self.key})

	def copy(self, shallow=True):
		"""
		Copies the dataset, making a new version with a unique key


		:param bool shallow:  Shallow copy: does not copy the result file, but
		instead refers to the same file as the original dataset did
		:return Dataset:  Copied dataset
		"""
		parameters = self.parameters.copy()

		# a key is partially based on the parameters. so by setting these extra
		# attributes, we also ensure a unique key will be generated for the
		# copy
		# possibly todo: don't use time for uniqueness (but one shouldn't be
		# copying a dataset multiple times per microsecond, that's not what
		# this is for)
		parameters["copied_from"] = self.key
		parameters["copied_at"] = time.time()

		copy = DataSet(parameters=parameters, db=self.db, extension=self.result_file.split(".")[-1], type=self.type)
		for field in self.data:
			if field in ("id", "key", "timestamp", "job", "parameters", "result_file"):
				continue

			copy.__setattr__(field, self.data[field])

		if shallow:
			# use the same result file
			copy.result_file = self.result_file
		else:
			# copy to new file with new key
			shutil.copy(self.get_results_path(), copy.get_results_path())

		if self.is_finished():
			copy.finish(self.num_rows)

		return copy

	def delete(self):
		"""
		Delete the dataset, and all its children

		Deletes both database records and result files. Note that manipulating
		a dataset object after it has been deleted is undefined behaviour.
		"""
		# first, recursively delete children
		children = self.db.fetchall("SELECT * FROM datasets WHERE key_parent = %s", (self.key,))
		for child in children:
			child = DataSet(key=child["key"], db=self.db)
			child.delete()

		# delete from database
		self.db.execute("DELETE FROM datasets WHERE key = %s", (self.key,))

		# delete from drive
		try:
			self.get_results_path().unlink()
		except FileNotFoundError:
			# already deleted, apparently
			pass

	def is_finished(self):
		"""
		Check if dataset is finished
		:return bool:
		"""
		return self.data["is_finished"] == True

	def is_rankable(self, multiple_items=True):
		"""
		Determine if a dataset is rankable

		Rankable means that it is a CSV file with 'date' and 'value' columns
		as well as one or more item label columns

		:param bool multiple_items:  Consider datasets with multiple items per
		item (e.g. word_1, word_2, etc)?

		:return bool:  Whether the dataset is rankable or not
		"""
		if self.get_results_path().suffix != ".csv" or not self.get_results_path().exists():
			return False

		column_options = {"date", "value", "item"}
		if multiple_items:
			column_options.add("word_1")

		with self.get_results_path().open(encoding="utf-8") as infile:
			reader = csv.DictReader(infile)
			try:
				return len(set(reader.fieldnames) & column_options) >= 3
			except (TypeError, ValueError):
				return False

	def get_parameters(self):
		"""
		Get dataset parameters

		The dataset parameters are stored as JSON in the database - parse them
		and return the resulting object

		:return:  Dataset parameters as originally stored
		"""
		try:
			return json.loads(self.data["parameters"])
		except json.JSONDecodeError:
			return {}

	def update_label(self, label):
		"""
		Update label for this dataset

		:param str label:  New label
		:return str:  The new label, as returned by get_label
		"""
		self.parameters["label"] = label

		self.db.update("datasets", data={"parameters": json.dumps(self.parameters)}, where={"key": self.key})
		return self.get_label()

	def get_label(self, parameters=None, default="Query"):
		"""
		Generate a readable label for the dataset

		:param dict parameters:  Parameters of the dataset
		:param str default:  Label to use if it cannot be inferred from the
		parameters

		:return str:  Label
		"""
		if not parameters:
			parameters = self.parameters

		if parameters.get("label"):
			return parameters["label"]
		elif parameters.get("body_query") and parameters["body_query"] != "empty":
			return parameters["body_query"]
		elif parameters.get("body_match") and parameters["body_match"] != "empty":
			return parameters["body_match"]
		elif parameters.get("subject_query") and parameters["subject_query"] != "empty":
			return parameters["subject_query"]
		elif parameters.get("subject_match") and parameters["subject_match"] != "empty":
			return parameters["subject_match"]
		elif parameters.get("query"):
			label = parameters["query"] if len(parameters["query"]) < 30 else parameters["query"][:25] + "..."
			# Some legacy datasets have lists as query data
			if isinstance(label, list):
				label = ", ".join(label)
			label = label.strip().replace("\n", ", ")
			return label
		elif parameters.get("country_flag") and parameters["country_flag"] != "all":
			return "Flag: %s" % parameters["country_flag"]
		elif parameters.get("country_name") and parameters["country_name"] != "all":
			return "Country: %s" % parameters["country_name"]
		elif parameters.get("filename"):
			return parameters["filename"]
		elif parameters.get("board") and "datasource" in parameters:
			return parameters["datasource"] + "/" + parameters["board"]
		else:
			return default

	def reserve_result_file(self, parameters=None, extension="csv"):
		"""
		Generate a unique path to the results file for this dataset

		This generates a file name for the data file of this dataset, and makes sure
		no file exists or will exist at that location other than the file we
		expect (i.e. the data for this particular dataset).

		:param str extension: File extension, "csv" by default
		:param parameters:  Dataset parameters
		:return bool:  Whether the file path was successfully reserved
		"""
		if self.data["is_finished"]:
			raise RuntimeError("Cannot reserve results file for a finished dataset")

		# Use 'random' for random post queries
		if "random_amount" in parameters and int(parameters["random_amount"]) > 0:
			file = 'random-' + str(parameters["random_amount"]) + '-' + self.data["key"]
		# Use country code for country flag queries
		elif "country_flag" in parameters and parameters["country_flag"] != 'all':
			file = 'countryflag-' + str(parameters["country_flag"]) + '-' + self.data["key"]
		# Use the query string for all other queries
		else:
			query_bit = self.data["query"].replace(" ", "-").lower()
			query_bit = re.sub(r"[^a-z0-9\-]", "", query_bit)
			query_bit = query_bit[:100]  # Crop to avoid OSError
			file = query_bit + "-" + self.data["key"]
			file = re.sub(r"[-]+", "-", file)

		path = self.folder.joinpath(file + "." + extension.lower())
		index = 1
		while path.is_file():
			path = self.folder.joinpath(file + "-" + str(index) + "." + extension.lower())
			index += 1

		file = path.name
		updated = self.db.update("datasets", where={"query": self.data["query"], "key": self.data["key"]},
								 data={"result_file": file})
		self.data["result_file"] = file
		return updated > 0

	def get_key(self, query, parameters, parent=""):
		"""
		Generate a unique key for this dataset that can be used to identify it

		The key is a hash of a combination of the query string and parameters.
		You never need to call this, really: it's used internally.

		:param str query:  Query string
		:param parameters:  Dataset parameters
		:param parent: Parent dataset's key (if applicable)

		:return str:  Dataset key
		"""
		# Return a unique key if random posts are queried
		if parameters.get("random_amount", None):
			random_int = str(random.randint(1, 10000000))
			return hashlib.md5(random_int.encode("utf-8")).hexdigest()

		# Return a hash based on parameters for other datasets
		else:
			# we're going to use the hash of the parameters to uniquely identify
			# the dataset, so make sure it's always in the same order, or we might
			# end up creating multiple keys for the same dataset if python
			# decides to return the dict in a different order
			param_key = collections.OrderedDict()
			for key in sorted(parameters):
				param_key[key] = parameters[key]

			parent_key = str(parent) if parent else ""
			plain_key = repr(param_key) + str(query) + parent_key
			return hashlib.md5(plain_key.encode("utf-8")).hexdigest()

	def get_status(self):
		"""
		Get Dataset status

		:return string: Dataset status
		"""
		return self.data["status"]

	def update_status(self, status, is_final=False):
		"""
		Update dataset status

		The status is a string that may be displayed to a user to keep them
		updated and informed about the progress of a dataset. No memory is kept
		of earlier dataset statuses; the current status is overwritten when
		updated.

		Statuses are also written to the dataset log file.

		:param string status:  Dataset status
		:param bool is_final:  If this is `True`, subsequent calls to this
		method while the object is instantiated will not update the dataset
		status.
		:return bool:  Status update successful?
		"""
		if self.no_status_updates:
			return

		# for presets, copy the updated status to the preset(s) this is part of
		if self.preset_parent is None:
			self.preset_parent = [parent for parent in self.get_genealogy() if parent.type.find("preset-") == 0 and parent.key != self.key][:1]

		if self.preset_parent:
			for preset_parent in self.preset_parent:
				if not preset_parent.is_finished():
					preset_parent.update_status(status)

		self.data["status"] = status
		updated = self.db.update("datasets", where={"key": self.data["key"]}, data={"status": status})

		if is_final:
			self.no_status_updates = True

		self.log(status)

		return updated > 0

	def update_version(self, version):
		"""
		Update software version used for this dataset

		This can be used to verify the code that was used to process this dataset.

		:param string version:  Version identifier
		:return bool:  Update successul?
		"""
		self.data["software_version"] = version
		updated = self.db.update("datasets", where={"key": self.data["key"]}, data={
			"software_version": version,
			"software_file": backend.all_modules.processors.get(self.data["type"]).filepath
		})

		return updated > 0

	def delete_parameter(self, parameter):
		"""
		Delete a parameter from the dataset metadata

		:param string parameter:  Parameter to delete
		:return bool:  Update successul?
		"""
		parameters = self.parameters
		if parameter in parameters:
			del parameters[parameter]
		else:
			return False

		updated = self.db.update("datasets", where={"key": self.data["key"]},
								 data={"parameters": json.dumps(parameters)})
		self.parameters = parameters

		return updated > 0

	def get_version_url(self, file):
		"""
		Get a versioned github URL for the version this dataset was processed with

		:param file:  File to link within the repository
		:return:  URL, or an empty string
		"""
		if not self.data["software_version"] or not config.GITHUB_URL:
			return ""

		return config.GITHUB_URL + "/blob/" + self.data["software_version"] + self.data.get("software_file", "")

	def top_parent(self):
		"""
		Get root dataset

		Traverses the tree of datasets this one is part of until it finds one
		with no source_dataset dataset, then returns that dataset.

		:return Dataset: Parent dataset
		"""
		genealogy = self.get_genealogy()
		return genealogy[0]

	def get_genealogy(self):
		"""
		Get genealogy of this dataset

		Creates a list of DataSet objects, with the first one being the
		'top' dataset, and each subsequent one being a child of the previous
		one, ending with the current dataset.

		:return list:  Dataset genealogy, oldest dataset first
		"""
		if self.genealogy:
			return self.genealogy

		key_parent = self.key_parent
		genealogy = []

		while key_parent:
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

	def get_all_children(self, recursive=True):
		"""
		Get all children of this dataset

		Results are returned as a non-hierarchical list, i.e. the result does
		not reflect the actual dataset hierarchy (but all datasets in the
		result will have the original dataset as an ancestor somewhere)

		:return list:  List of DataSets
		"""
		children = [DataSet(data=record, db=self.db) for record in self.db.fetchall("SELECT * FROM datasets WHERE key_parent = %s", (self.key,))]
		results = children.copy()
		if recursive:
			for child in children:
				results += child.get_all_children(recursive)

		return results

	def get_breadcrumbs(self):
		"""
		Get breadcrumbs navlink for use in permalinks

		Returns a string representing this dataset's genealogy that may be used
		to uniquely identify it.

		:return str: Nav link
		"""
		genealogy = self.get_genealogy()

		return ",".join([dataset.key for dataset in genealogy])

	def get_compatible_processors(self):
		"""
		Get list of processors compatible with this dataset

		Checks whether this dataset type is one that is listed as being accepted
		by the processor, for each known type: if the processor does not
		specify accepted types (via the `is_compatible_with` method), it is
		assumed it accepts any top-level datasets

		:return dict:  Compatible processors, `name => class` mapping
		"""
		processors = backend.all_modules.processors

		available = {}
		for processor_type, processor in processors.items():
			if processor_type.endswith("-search"):
				continue

			# consider a processor compatible if its is_compatible_with
			# method returns True *or* if it has no explicit compatibility
			# check and this dataset is top-level (i.e. has no parent)
			if (not hasattr(processor, "is_compatible_with") and not self.key_parent) \
					or (hasattr(processor, "is_compatible_with") and processor.is_compatible_with(self)):
				available[processor_type] = processor

		return available

	def get_own_processor(self):
		"""
		Get the processor class that produced this dataset

		:return:  Processor class, or `None` if not available.
		"""
		return backend.all_modules.processors.get(self.data.get("type"))


	def get_available_processors(self):
		"""
		Get list of processors that may be run for this dataset

		Returns all compatible processors except for those that are already
		queued or finished and have no options. Processors that have been
		run but have options are included so they may be run again with a
		different configuration

		:return dict:  Available processors, `name => properties` mapping
		"""
		if self.available_processors:
			return self.available_processors

		processors = self.get_compatible_processors()

		for analysis in self.children:
			if analysis.type not in processors:
				continue

			if not processors[analysis.type].get_options():
				del processors[analysis.type]

		self.available_processors = processors
		return processors

	def link_job(self, job):
		"""
		Link this dataset to a job ID

		Updates the dataset data to include a reference to the job that will be
		executing (or has already executed) this job.

		Note that if no job can be found for this dataset, this method silently
		fails.

		:param Job job:  The job that will run this dataset

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

		self.db.update("datasets", where={"key": self.key}, data={"job": job.data["id"]})

	def link_parent(self, key_parent):
		"""
		Set source_dataset key for this dataset

		:param key_parent:  Parent key. Not checked for validity
		"""
		self.db.update("datasets", where={"key": self.key}, data={"key_parent": key_parent})

	def get_parent(self):
		"""
		Get parent dataset

		:return DataSet:  Parent dataset, or `None` if not applicable
		"""
		return DataSet(key=self.key_parent, db=self.db) if self.key_parent else None

	def detach(self):
		"""
		Makes the datasets standalone, i.e. not having any source_dataset dataset
		"""
		self.link_parent("")

	def is_dataset(self):
		"""
		Easy way to confirm this is a dataset.
		Used for checking processor and dataset compatibility,
		which needs to handle both processors and datasets.
		"""
		return True

	def is_top_dataset(self):
		"""
		Easy way to confirm this is a top dataset.
		Used for checking processor and dataset compatibility,
		which needs to handle both processors and datasets.
		"""
		if self.get_parent():
			return False
		return True

	def get_extension(self):
		"""
		Gets the file extention this dataset produces.
		Also checks whether the results file exists.
		Used for checking processor and dataset compatibility.

		"""

		if self.get_results_path().exists():
			return self.get_results_path().suffix[1:]
		return False

	def __getattr__(self, attr):
		"""
		Getter so we don't have to use .data all the time

		:param attr:  Data key to get
		:return:  Value
		"""

		if attr in dir(self):
			# an explicitly defined attribute should always be called in favour
			# of this passthrough
			attribute = getattr(self, attr)
			return attribute
		elif attr in self.data:
			return self.data[attr]
		else:
			raise KeyError("DataSet instance has no attribute %s" % attr)

	def __setattr__(self, attr, value):
		"""
		Setter so we can flexibly update the database

		Also updates internal data stores (.data etc). If the attribute is
		unknown, it is stored within the 'parameters' attribute.

		:param str attr:  Attribute to update
		:param value:  New value
		"""

		# don't override behaviour for *actual* class attributes
		if attr in dir(self):
			super().__setattr__(attr, value)
			return

		if attr not in self.data:
			self.parameters[attr] = value
			attr = "parameters"
			value = self.parameters

		if attr == "parameters":
			value = json.dumps(value)

		self.db.update("datasets", where={"key": self.key}, data={attr: value})

		self.data[attr] = value

		if attr == "parameters":
			self.parameters = json.loads(value)
