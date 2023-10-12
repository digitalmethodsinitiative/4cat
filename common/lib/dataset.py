import collections
import itertools
import datetime
import hashlib
import fnmatch
import shutil
import json
import time
import csv
import re

from pathlib import Path

import backend
from common.config_manager import config
from common.lib.job import Job, JobNotFoundException
from common.lib.helpers import get_software_version, NullAwareTextIOWrapper, convert_to_int
from common.lib.fourcat_module import FourcatModule
from common.lib.exceptions import ProcessorInterruptedException, DataSetException, MapItemException


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
	# Attributes must be created here to ensure getattr and setattr work properly
	data = None
	key = ""

	children = None
	available_processors = None
	genealogy = None
	preset_parent = None
	parameters = None

	owners = None
	tagged_owners = None

	db = None
	folder = None
	is_new = True

	no_status_updates = False
	staging_areas = None
	queue_position = None

	def __init__(self, parameters=None, key=None, job=None, data=None, db=None, parent='', extension=None,
				 type=None, is_private=True, owner="anonymous"):
		"""
		Create new dataset object

		If the dataset is not in the database yet, it is added.

		:param parameters:  Parameters, e.g. search query, date limits, et cetera
		:param db:  Database connection
		"""
		self.db = db
		self.folder = config.get('PATH_ROOT').joinpath(config.get('PATH_DATA'))
		# Ensure mutable attributes are set in __init__ as they are unique to each DataSet
		self.data = {}
		self.parameters = {}
		self.children = []
		self.available_processors = {}
		self.genealogy = []
		self.staging_areas = []

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
				"creator": owner,
				"status": "",
				"type": type,
				"timestamp": int(time.time()),
				"is_finished": False,
				"is_private": is_private,
				"software_version": get_software_version(),
				"software_file": "",
				"num_rows": 0,
				"progress": 0.0,
				"key_parent": parent
			}
			self.parameters = parameters

			self.db.insert("datasets", data=self.data)
			self.refresh_owners()
			self.add_owner(owner)

			# Find desired extension from processor if not explicitly set
			if extension is None:
				own_processor = self.get_own_processor()
				if own_processor:
					extension = own_processor.get_extension(parent_dataset=DataSet(key=parent, db=db) if parent else None)
				# Still no extension, default to 'csv'
				if not extension:
					extension = "csv"

			# Reserve filename and update data['result_file']
			self.reserve_result_file(parameters, extension)

		# retrieve analyses and processors that may be run for this dataset
		analyses = self.db.fetchall("SELECT * FROM datasets WHERE key_parent = %s ORDER BY timestamp ASC", (self.key,))
		self.children = sorted([DataSet(data=analysis, db=self.db) for analysis in analyses],
							   key=lambda dataset: dataset.is_finished(), reverse=True)

		self.refresh_owners()
		self.get_place_in_queue()

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

	def get_results_folder_path(self):
		"""
		Get path to folder containing accompanying results

		Returns a path that may not yet be created

		:return Path:  A path to the results file
		"""
		return self.folder.joinpath("folder_" + self.key)

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

	def iterate_items(self, processor=None, bypass_map_item=False, warn_unmappable=True):
		"""
		A generator that iterates through a CSV or NDJSON file

		If a reference to a processor is provided, with every iteration,
		the processor's 'interrupted' flag is checked, and if set a
		ProcessorInterruptedException is raised, which by default is caught
		in the worker and subsequently stops execution gracefully.

		Processors can define a method called `map_item` that can be used to
		map an item from the dataset file before it is processed any further
		this is slower than storing the data file in the right format to begin
		with but not all data sources allow for easy 'flat' mapping of items,
		e.g. tweets are nested objects when retrieved from the twitter API
		that are easier to store as a JSON file than as a flat CSV file, and
		it would be a shame to throw away that data.

		There are two file types that can be iterated (currently): CSV files
		and NDJSON (newline-delimited JSON) files. In the future, one could
		envision adding a pathway to retrieve items from e.g. a MongoDB
		collection directly instead of from a static file

		:param BasicProcessor processor:  A reference to the processor
		iterating the dataset.
		:param bool bypass_map_item:  If set to `True`, this ignores any
		`map_item` method of the datasource when returning items.
		:return generator:  A generator that yields each item as a dictionary
		"""
		unmapped_items = False
		path = self.get_results_path()

		# see if an item mapping function has been defined
		# open question if 'source_dataset' shouldn't be an attribute of the dataset
		# instead of the processor...
		item_mapper = False
		own_processor = self.get_own_processor()
		if not bypass_map_item and own_processor is not None:
			if own_processor.map_item_method_available(dataset=self):
				item_mapper = True

		# go through items one by one, optionally mapping them
		if path.suffix.lower() == ".csv":
			with path.open("rb") as infile:
				csv_parameters = own_processor.get_csv_parameters(csv) if own_processor else {}

				wrapped_infile = NullAwareTextIOWrapper(infile, encoding="utf-8")
				reader = csv.DictReader(wrapped_infile, **csv_parameters)

				for i, item in enumerate(reader):
					if hasattr(processor, "interrupted") and processor.interrupted:
						raise ProcessorInterruptedException("Processor interrupted while iterating through CSV file")

					if item_mapper:
						try:
							item = own_processor.get_mapped_item(item)
						except MapItemException as e:
							if warn_unmappable:
								self.warn_unmappable_item(i, processor, e, warn_admins=unmapped_items is False)
								unmapped_items = True
							continue

					yield item

		elif path.suffix.lower() == ".ndjson":
			# in this format each line in the file is a self-contained JSON
			# file
			with path.open(encoding="utf-8") as infile:
				for i, line in enumerate(infile):
					if hasattr(processor, "interrupted") and processor.interrupted:
						raise ProcessorInterruptedException("Processor interrupted while iterating through NDJSON file")

					item = json.loads(line)
					if item_mapper:
						try:
							item = own_processor.get_mapped_item(item)
						except MapItemException as e:
							if warn_unmappable:
								self.warn_unmappable_item(i, processor, e, warn_admins=unmapped_items is False)
								unmapped_items = True
							continue

					yield item

		else:
			raise NotImplementedError("Cannot iterate through %s file" % path.suffix)

	def iterate_mapped_items(self, processor=None, warn_unmappable=True):
		"""
		Wrapper for iterate_items that returns both the original item and the mapped item (or else the same identical item).
		No extension check is performed here as the point is to be able to handle the original object and save as an appropriate
		filetype.

		:param BasicProcessor processor:  A reference to the processor
		iterating the dataset.
		:return generator:  A generator that yields a tuple with the unmapped item followed by the mapped item
		"""
		unmapped_items = False
		# Collect item_mapper for use with filter
		item_mapper = False
		own_processor = self.get_own_processor()
		if own_processor.map_item_method_available(dataset=self):
			item_mapper = True

		# Loop through items
		for i, item in enumerate(self.iterate_items(processor=processor, bypass_map_item=True)):
			# Save original to yield
			original_item = item.copy()

			# Map item
			if item_mapper:
				try:
					mapped_item = own_processor.get_mapped_item(item)
				except MapItemException as e:
					if warn_unmappable:
						self.warn_unmappable_item(i, processor, e, warn_admins=unmapped_items is False)
						unmapped_items = True
					continue
			else:
				mapped_item = original_item

			# Yield the two items
			yield original_item, mapped_item

	def get_item_keys(self, processor=None):
		"""
		Get item attribute names

		It can be useful to know what attributes an item in the dataset is
		stored with, e.g. when one wants to produce a new dataset identical
		to the source_dataset one but with extra attributes. This method provides
		these, as a list.

		:param BasicProcessor processor:  A reference to the processor
		asking for the item keys, to pass on to iterate_itesm
		:return list:  List of keys, may be empty if there are no items in the
		  dataset
		"""

		items = self.iterate_items(processor, warn_unmappable=False)
		try:
			keys = list(items.__next__().keys())
		except StopIteration:
			return []
		finally:
			del items

		return keys

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

		# Storing the staging area with the dataset so that it can be removed later
		self.staging_areas.append(results_path)

		return results_path

	def remove_staging_areas(self):
		"""
		Remove any staging areas that were created and all files contained in them.
		"""
		# Remove DataSet staging areas
		if self.staging_areas:
			for staging_area in self.staging_areas:
				if staging_area.is_dir():
					shutil.rmtree(staging_area)

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
					   data={"is_finished": True, "num_rows": num_rows, "progress": 1.0})
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
		self.data["progress"] = 0

		self.db.update("datasets", data={
			"timestamp": self.data["timestamp"],
			"is_finished": self.data["is_finished"],
			"num_rows": self.data["num_rows"],
			"status": self.data["status"],
			"progress": 0
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

		# make sure ownership is also copied
		copy.copy_ownership_from(self)

		return copy

	def delete(self, commit=True):
		"""
		Delete the dataset, and all its children

		Deletes both database records and result files. Note that manipulating
		a dataset object after it has been deleted is undefined behaviour.

		:param commit bool:  Commit SQL DELETE query?
		"""
		# first, recursively delete children
		children = self.db.fetchall("SELECT * FROM datasets WHERE key_parent = %s", (self.key,))
		for child in children:
			try:
				child = DataSet(key=child["key"], db=self.db)
				child.delete(commit=commit)
			except TypeError:
				# dataset already deleted - race condition?
				pass

		# delete from database
		self.db.delete("datasets", where={"key": self.key}, commit=commit)
		self.db.delete("datasets_owners", where={"key": self.key}, commit=commit)
		self.db.delete("users_favourites", where={"key": self.key}, commit=commit)

		# delete from drive
		try:
			self.get_results_path().unlink()
			if self.get_results_path().with_suffix(".log").exists():
				self.get_results_path().with_suffix(".log").unlink()
			if self.get_results_folder_path().exists():
				shutil.rmtree(self.get_results_folder_path())
		except FileNotFoundError:
			# already deleted, apparently
			pass

	def update_children(self, **kwargs):
		"""
		Update an attribute for all child datasets

		Can be used to e.g. change the owner, version, finished status for all
		datasets in a tree

		:param kwargs:  Parameters corresponding to known dataset attributes
		"""
		children = self.db.fetchall("SELECT * FROM datasets WHERE key_parent = %s", (self.key,))
		for child in children:
			child = DataSet(key=child["key"], db=self.db)
			for attr, value in kwargs.items():
				child.__setattr__(attr, value)

			child.update_children(**kwargs)

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
			own_processor = self.get_own_processor()
			csv_parameters = own_processor.get_csv_parameters(csv) if own_processor else {}

			reader = csv.DictReader(infile, **csv_parameters)
			try:
				return len(set(reader.fieldnames) & column_options) >= 3
			except (TypeError, ValueError):
				return False

	def is_accessible_by(self, username, role="owner"):
		"""
		Check if dataset has given user as owner

		:param str|User username: Username to check for
		:return bool:
		"""
		if type(username) is not str:
			if hasattr(username, "get_id"):
				username = username.get_id()
			else:
				raise TypeError("User must be a str or User object")

		# 'normal' owners
		if username in [owner for owner, meta in self.owners.items() if (role is None or meta["role"] == role)]:
			return True

		# owners that are owner by being part of a tag
		if username in itertools.chain(*[tagged_owners for tag, tagged_owners in self.tagged_owners.items() if (role is None or self.owners[f"tag:{tag}"]["role"] == role)]):
			return True

		return False

	def get_owners_users(self, role="owner"):
		"""
		Get list of dataset owners

		This returns a list of *users* that are considered owners. Tags are
		transparently replaced with the users with that tag.

		:param str|None role:  Role to check for. If `None`, all owners are
		returned regardless of role.

		:return set:  De-duplicated owner list
		"""
		# 'normal' owners
		owners = [owner for owner, meta in self.owners.items() if
				  (role is None or meta["role"] == role) and not owner.startswith("tag:")]

		# owners that are owner by being part of a tag
		owners.extend(itertools.chain(*[tagged_owners for tag, tagged_owners in self.tagged_owners.items() if
									   role is None or self.owners[f"tag:{tag}"]["role"] == role]))

		# de-duplicate before returning
		return set(owners)

	def get_owners(self, role="owner"):
		"""
		Get list of dataset owners

		This returns a list of all owners, and does not transparently resolve
		tags (like `get_owners_users` does).

		:param str|None role:  Role to check for. If `None`, all owners are
		returned regardless of role.

		:return set:  De-duplicated owner list
		"""
		return [owner for owner, meta in self.owners.items() if (role is None or meta["role"] == role)]

	def add_owner(self, username, role="owner"):
		"""
		Set dataset owner

		If the user is already an owner, but with a different role, the role is
		updated. If the user is already an owner with the same role, nothing happens.

		:param str|User username:  Username to set as owner
		:param str|None role:  Role to add user with.
		"""
		if type(username) is not str:
			if hasattr(username, "get_id"):
				username = username.get_id()
			else:
				raise TypeError("User must be a str or User object")

		if username not in self.owners:
			self.owners[username] = {
				"name": username,
				"key": self.key,
				"role": role
			}
			self.db.insert("datasets_owners", data=self.owners[username], safe=True)

		elif username in self.owners and self.owners[username]["role"] != role:
			self.db.update("datasets_owners", data={"role": role}, where={"name": username, "key": self.key})
			self.owners[username]["role"] = role

		if username.startswith("tag:"):
			# this is a bit more complicated than just adding to the list of
			# owners, so do a full refresh
			self.refresh_owners()

		# make sure children's owners remain in sync
		for child in self.children:
			child.add_owner(username, role)
			# not recursive, since we're calling it from recursive code!
			child.copy_ownership_from(self, recursive=False)

	def remove_owner(self, username):
		"""
		Remove dataset owner

		If no owner is set, the dataset is assigned to the anonymous user.
		If the user is not an owner, nothing happens.

		:param str|User username:  Username to set as owner
		"""
		if type(username) is not str:
			if hasattr(username, "get_id"):
				username = username.get_id()
			else:
				raise TypeError("User must be a str or User object")

		if username in self.owners:
			del self.owners[username]
			self.db.delete("datasets_owners", where={"name": username, "key": self.key})

			if not self.owners:
				self.add_owner("anonymous")

		if username in self.tagged_owners:
			del self.tagged_owners[username]

		# make sure children's owners remain in sync
		for child in self.children:
			child.remove_owner(username)
			# not recursive, since we're calling it from recursive code!
			child.copy_ownership_from(self, recursive=False)

	def refresh_owners(self):
		"""
		Update internal owner cache

		This makes sure that the list of *users* and *tags* which can access the
		dataset is up to date.
		"""
		self.owners = {owner["name"]: owner for owner in self.db.fetchall("SELECT * FROM datasets_owners WHERE key = %s", (self.key,))}

		# determine which users (if any) are owners of the dataset by having a
		# tag that is listed as an owner
		owner_tags = [name[4:] for name in self.owners if name.startswith("tag:")]
		if owner_tags:
			tagged_owners = self.db.fetchall("SELECT name, tags FROM users WHERE tags ?| %s ", (owner_tags,))
			self.tagged_owners = {
				owner_tag: [user["name"] for user in tagged_owners if owner_tag in user["tags"]]
				for owner_tag in owner_tags
			}
		else:
			self.tagged_owners = {}

	def copy_ownership_from(self, dataset, recursive=True):
		"""
		Copy ownership

		This is useful to e.g. make sure a dataset's ownership stays in sync
		with its parent

		:param Dataset dataset:  Parent to copy from
		:return:
		"""
		self.db.delete("datasets_owners", where={"key": self.key}, commit=False)

		for role in ("owner", "viewer"):
			owners = dataset.get_owners(role=role)
			for owner in owners:
				self.db.insert("datasets_owners", data={"key": self.key, "name": owner, "role": role}, commit=False)

		self.db.commit()
		if recursive:
			for child in self.children:
				child.copy_ownership_from(self, recursive=recursive)

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

	def get_columns(self):
		"""
		Returns the dataset columns.

		Useful for processor input forms. Can deal with both CSV and NDJSON
		files, the latter only if a `map_item` function is available in the
		processor that generated it. While in other cases one could use the
		keys of the JSON object, this is not always possible in follow-up code
		that uses the 'column' names, so for consistency this function acts as
		if no column can be parsed if no `map_item` function exists.

		:return list:  List of dataset columns; empty list if unable to parse
		"""

		if not self.get_results_path().exists():
			# no file to get columns from
			return False

		if (self.get_results_path().suffix.lower() == ".csv") or (self.get_results_path().suffix.lower() == ".ndjson" and self.get_own_processor() is not None and self.get_own_processor().map_item_method_available(dataset=self)):
			return self.get_item_keys(processor=self.get_own_processor())
		else:
			# Filetype not CSV or an NDJSON with `map_item`
			return []

	def get_annotation_fields(self):
		"""
		Retrieves the saved annotation fields for this dataset.
		:return dict: The saved annotation fields.
		"""

		annotation_fields = self.db.fetchone("SELECT annotation_fields FROM datasets WHERE key = %s;", (self.top_parent().key,))
		
		if annotation_fields and annotation_fields.get("annotation_fields"):
			annotation_fields = json.loads(annotation_fields["annotation_fields"])
		else:
			annotation_fields = {}

		return annotation_fields

	def get_annotations(self):
		"""
		Retrieves the annotations for this dataset.
		return dict: The annotations
		"""

		annotations = self.db.fetchone("SELECT annotations FROM annotations WHERE key = %s;", (self.top_parent().key,))

		if annotations and annotations.get("annotations"):
			return json.loads(annotations["annotations"])
		else:
			return None

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
		elif "datasource" in parameters and parameters["datasource"] in backend.all_modules.datasources:
			return backend.all_modules.datasources[parameters["datasource"]]["name"] + " Dataset"
		else:
			return default

	def change_datasource(self, datasource):
		"""
		Change the datasource type for this dataset

		:param str label:  New datasource type
		:return str:  The new datasource type
		"""

		self.parameters["datasource"] = datasource

		self.db.update("datasets", data={"parameters": json.dumps(self.parameters)}, where={"key": self.key})
		return datasource

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
		# Return a hash based on parameters
		# we're going to use the hash of the parameters to uniquely identify
		# the dataset, so make sure it's always in the same order, or we might
		# end up creating multiple keys for the same dataset if python
		# decides to return the dict in a different order
		param_key = collections.OrderedDict()
		for key in sorted(parameters):
			param_key[key] = parameters[key]

		# this ensures a different key for the same query if not queried
		# at the exact same second. Since the same query may return
		# different results when done at different times, getting a
		# duplicate key is not actually always desirable. The resolution
		# of this salt could be experimented with...
		param_key["_salt"] = int(time.time())

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

	def update_progress(self, progress):
		"""
		Update dataset progress

		The progress can be used to indicate to a user how close the dataset
		is to completion.

		:param float progress:  Between 0 and 1.
		:return:
		"""
		progress = min(1, max(0, progress))  # clamp
		if type(progress) is int:
			progress = float(progress)

		self.data["progress"] = progress
		updated = self.db.update("datasets", where={"key": self.data["key"]}, data={"progress": progress})
		return updated > 0

	def get_progress(self):
		"""
		Get dataset progress

		:return float:  Progress, between 0 and 1
		"""
		return self.data["progress"]

	def finish_with_error(self, error):
		"""
		Set error as final status, and finish with 0 results

		This is a convenience function to avoid having to repeat
		"update_status" and "finish" a lot.

		:param str error:  Error message for final dataset status.
		:return:
		"""
		self.update_status(error, is_final=True)
		self.finish(0)

		return None

	def update_version(self, version):
		"""
		Update software version used for this dataset

		This can be used to verify the code that was used to process this dataset.

		:param string version:  Version identifier
		:return bool:  Update successul?
		"""
		try:
			# this fails if the processor type is unknown
			# edge case, but let's not crash...
			processor_path = backend.all_modules.processors.get(self.data["type"]).filepath
		except AttributeError:
			processor_path = ""

		updated = self.db.update("datasets", where={"key": self.data["key"]}, data={
			"software_version": version,
			"software_file": processor_path
		})

		return updated > 0

	def delete_parameter(self, parameter, instant=True):
		"""
		Delete a parameter from the dataset metadata

		:param string parameter:  Parameter to delete
		:param bool instant:  Also delete parameters in this instance object?
		:return bool:  Update successul?
		"""
		parameters = self.parameters.copy()
		if parameter in parameters:
			del parameters[parameter]
		else:
			return False

		updated = self.db.update("datasets", where={"key": self.data["key"]},
								 data={"parameters": json.dumps(parameters)})

		if instant:
			self.parameters = parameters

		return updated > 0

	def get_version_url(self, file):
		"""
		Get a versioned github URL for the version this dataset was processed with

		:param file:  File to link within the repository
		:return:  URL, or an empty string
		"""
		if not self.data["software_version"] or not config.get("4cat.github_url"):
			return ""

		return config.get("4cat.github_url") + "/blob/" + self.data["software_version"] + self.data.get("software_file", "")

	def top_parent(self):
		"""
		Get root dataset

		Traverses the tree of datasets this one is part of until it finds one
		with no source_dataset dataset, then returns that dataset.

		:return Dataset: Parent dataset
		"""
		genealogy = self.get_genealogy()
		return genealogy[0]

	def get_genealogy(self, inclusive=False):
		"""
		Get genealogy of this dataset

		Creates a list of DataSet objects, with the first one being the
		'top' dataset, and each subsequent one being a child of the previous
		one, ending with the current dataset.

		:return list:  Dataset genealogy, oldest dataset first
		"""
		if self.genealogy and not inclusive:
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

	def nearest(self, type_filter):
		"""
		Return nearest dataset that matches the given type

		Starting with this dataset, traverse the hierarchy upwards and return
		whichever dataset matches the given type.

		:param str type_filter:  Type filter. Can contain wildcards and is matched
		using `fnmatch.fnmatch`.
		:return:  Earliest matching dataset, or `None` if none match.
		"""
		genealogy = self.get_genealogy(inclusive=True)
		for dataset in reversed(genealogy):
			if fnmatch.fnmatch(dataset.type, type_filter):
				return dataset

		return None

	def get_breadcrumbs(self):
		"""
		Get breadcrumbs navlink for use in permalinks

		Returns a string representing this dataset's genealogy that may be used
		to uniquely identify it.

		:return str: Nav link
		"""
		if self.genealogy:
			return ",".join([dataset.key for dataset in self.genealogy])
		else:
			# Collect keys only
			key_parent = self.key  # Start at the bottom
			genealogy = []

			while key_parent:
				try:
					parent = self.db.fetchone("SELECT key_parent FROM datasets WHERE key = %s", (key_parent,))
				except TypeError:
					break

				key_parent = parent["key_parent"]
				if key_parent:
					genealogy.append(key_parent)
				else:
					break

			genealogy.reverse()
			genealogy.append(self.key)
			return ",".join(genealogy)

	def get_compatible_processors(self, user=None):
		"""
		Get list of processors compatible with this dataset

		Checks whether this dataset type is one that is listed as being accepted
		by the processor, for each known type: if the processor does not
		specify accepted types (via the `is_compatible_with` method), it is
		assumed it accepts any top-level datasets

		:param str|User|None user:  User to get compatibility for. If set,
		use the user-specific config settings where available.

		:return dict:  Compatible processors, `name => class` mapping
		"""
		processors = backend.all_modules.processors

		available = {}
		for processor_type, processor in processors.items():
			if processor.is_from_collector():
				continue

			# consider a processor compatible if its is_compatible_with
			# method returns True *or* if it has no explicit compatibility
			# check and this dataset is top-level (i.e. has no parent)
			if (not hasattr(processor, "is_compatible_with") and not self.key_parent) \
					or (hasattr(processor, "is_compatible_with") and processor.is_compatible_with(self, user=user)):
				available[processor_type] = processor

		return available

	def get_place_in_queue(self):
		"""
		Determine dataset's position in queue

		If the dataset is already finished, the position is -1. Else, the
		position is the amount of datasets to be completed before this one will
		be processed. A position of 0 would mean that the dataset is currently
		being executed, or that the backend is not running.

		:return int:  Queue position
		"""
		if self.is_finished() or not self.data.get("job"):
			self.queue_position = -1
			return
		else:
			try:
				job = Job.get_by_ID(self.data["job"], self.db)
				self.queue_position = job.data["queue_ahead"]
			except JobNotFoundException:
				self.queue_position = -1

		return self.queue_position

	def get_own_processor(self):
		"""
		Get the processor class that produced this dataset

		:return:  Processor class, or `None` if not available.
		"""
		processor_type = self.parameters.get("type", self.data.get("type"))
		return backend.all_modules.processors.get(processor_type)


	def get_available_processors(self, user=None):
		"""
		Get list of processors that may be run for this dataset

		Returns all compatible processors except for those that are already
		queued or finished and have no options. Processors that have been
		run but have options are included so they may be run again with a
		different configuration

		:param str|User|None user:  User to get compatibility for. If set,
		use the user-specific config settings where available.

		:return dict:  Available processors, `name => properties` mapping
		"""
		if self.available_processors:
			return self.available_processors

		processors = self.get_compatible_processors(user=user)

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
		if self.key_parent:
			return False
		return True

	def is_expiring(self, user=None):
		"""
		Determine if dataset is set to expire

		Similar to `is_expired`, but checks if the dataset will be deleted in
		the future, not if it should be deleted right now.

		:param user:  User to use for configuration context. Provide to make
		sure configuration overrides for this user are taken into account.
		:return bool|int:  `False`, or the expiration date as a Unix timestamp.
		"""
		# has someone opted out of deleting this?
		if self.parameters.get("keep"):
			return False

		# is this dataset explicitly marked as expiring after a certain time?
		if self.parameters.get("expires-after"):
			return self.parameters.get("expires-after")

		# is the data source configured to have its datasets expire?
		expiration = config.get("datasources.expiration", {}, user=user)
		if not expiration.get(self.parameters.get("datasource")):
			return False

		# is there a timeout for this data source?
		if expiration.get(self.parameters.get("datasource")).get("timeout"):
			return self.timestamp + expiration.get(self.parameters.get("datasource")).get("timeout")

		return False

	def is_expired(self, user=None):
		"""
		Determine if dataset should be deleted

		Datasets can be set to expire, but when they should be deleted depends
		on a number of factor. This checks them all.

		:param user:  User to use for configuration context. Provide to make
		sure configuration overrides for this user are taken into account.
		:return bool:
		"""
		# has someone opted out of deleting this?
		if not self.is_expiring():
			return False

		# is this dataset explicitly marked as expiring after a certain time?
		future = time.time() + 3600  # ensure we don't delete datasets with invalid expiration times
		if self.parameters.get("expires-after") and convert_to_int(self.parameters["expires-after"], future) < time.time():
			return True

		# is the data source configured to have its datasets expire?
		expiration = config.get("datasources.expiration", {}, user=user)
		if not expiration.get(self.parameters.get("datasource")):
			return False

		# is the dataset older than the set timeout?
		if expiration.get(self.parameters.get("datasource")).get("timeout"):
			return self.timestamp + expiration[self.parameters.get("datasource")]["timeout"] < time.time()

		return False

	def is_from_collector(self):
		"""
		Check if this dataset was made by a processor that collects data, i.e.
		a search or import worker.

		:return bool:
		"""
		return self.type.endswith("-search") or self.type.endswith("-import")

	def get_extension(self):
		"""
		Gets the file extention this dataset produces.
		Also checks whether the results file exists.
		Used for checking processor and dataset compatibility.

		:return str extension:  Extension, e.g. `csv`
		"""
		if self.get_results_path().exists():
			return self.get_results_path().suffix[1:]

		return False

	def get_result_url(self):
		"""
		Gets the 4CAT frontend URL of a dataset file.

		Uses the FlaskConfig attributes (i.e., SERVER_NAME and
		SERVER_HTTPS) plus hardcoded '/result/'.
		TODO: create more dynamic method of obtaining url.
		"""
		filename = self.get_results_path().name
		url_to_file = ('https://' if config.get("flask.https") else 'http://') + \
						config.get("flask.server_name") + '/result/' + filename
		return url_to_file

	def warn_unmappable_item(self, item_count, processor=None, error_message=None, warn_admins=True):
		"""
		Log an item that is unable to be mapped and warn administrators.

		:param int item_count:			Item index
		:param Processor processor:		Processor calling function8
		"""
		dataset_error_message = f"MapItemException (item {item_count}): {'is unable to be mapped! Check raw datafile.' if error_message is None else error_message}"

		# Use processing dataset if available, otherwise use original dataset (which likely already has this error message)
		closest_dataset = processor.dataset if processor is not None and processor.dataset is not None else self
		# Log error to dataset log
		closest_dataset.log(dataset_error_message)

		if warn_admins:
			if processor is not None:
				processor.log.warning(f"Processor {processor.type} unable to map item all items for dataset {closest_dataset.key}.")
			elif hasattr(self.db, "log"):
				self.db.log.warning(f"Unable to map item all items for dataset {closest_dataset.key}.")
			else:
				# No other log available
				raise DataSetException(f"Unable to map item {item_count} for dataset {closest_dataset.key} and properly warn")

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
			raise AttributeError("DataSet instance has no attribute %s" % attr)

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
