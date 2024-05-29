import collections
import itertools
import datetime
import hashlib
import fnmatch
import random
import shutil
import json
import time
import csv
import re

from pathlib import Path

import backend
from common.config_manager import config
from common.lib.job import Job, JobNotFoundException
from common.lib.helpers import get_software_commit, NullAwareTextIOWrapper, convert_to_int
from common.lib.item_mapping import MappedItem, MissingMappedField, DatasetItem
from common.lib.fourcat_module import FourcatModule
from common.lib.exceptions import (ProcessorInterruptedException, DataSetException, DataSetNotFoundException,
								   MapItemException, MappedItemIncompleteException)


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
	_queue_position = None

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
				raise DataSetNotFoundException("DataSet() requires a valid dataset key for its 'key' argument, \"%s\" given" % key)

			query = current["query"]
		elif job is not None:
			current = self.db.fetchone("SELECT * FROM datasets WHERE parameters::json->>'job' = %s", (job,))
			if not current:
				raise DataSetNotFoundException("DataSet() requires a valid job ID for its 'job' argument")

			query = current["query"]
			self.key = current["key"]
		elif data is not None:
			current = data
			if "query" not in data or "key" not in data or "parameters" not in data or "key_parent" not in data:
				raise DataSetException("DataSet() requires a complete dataset record for its 'data' argument")

			query = current["query"]
			self.key = current["key"]
		else:
			if parameters is None:
				raise DataSetException("DataSet() requires either 'key', or 'parameters' to be given")

			if not type:
				raise DataSetException("Datasets must have their type set explicitly")

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
				"software_version": get_software_commit(),
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

	def _iterate_items(self, processor=None):
		"""
		A generator that iterates through a CSV or NDJSON file

		This is an internal method and should not be called directly. Rather,
		call iterate_items() and use the generated dictionary and its properties.

		If a reference to a processor is provided, with every iteration,
		the processor's 'interrupted' flag is checked, and if set a
		ProcessorInterruptedException is raised, which by default is caught
		in the worker and subsequently stops execution gracefully.

		There are two file types that can be iterated (currently): CSV files
		and NDJSON (newline-delimited JSON) files. In the future, one could
		envision adding a pathway to retrieve items from e.g. a MongoDB
		collection directly instead of from a static file

		:param BasicProcessor processor:  A reference to the processor
		iterating the dataset.
		:return generator:  A generator that yields each item as a dictionary
		"""
		path = self.get_results_path()

		# Yield through items one by one
		if path.suffix.lower() == ".csv":
			with path.open("rb") as infile:
				# Processor (that created this dataset) may have a custom CSV dialect and parameters
				own_processor = self.get_own_processor()
				csv_parameters = own_processor.get_csv_parameters(csv) if own_processor else {}

				wrapped_infile = NullAwareTextIOWrapper(infile, encoding="utf-8")
				reader = csv.DictReader(wrapped_infile, **csv_parameters)

				for item in reader:
					if hasattr(processor, "interrupted") and processor.interrupted:
						raise ProcessorInterruptedException("Processor interrupted while iterating through CSV file")

					yield item

		elif path.suffix.lower() == ".ndjson":
			# In NDJSON format each line in the file is a self-contained JSON
			with path.open(encoding="utf-8") as infile:
				for line in infile:
					if hasattr(processor, "interrupted") and processor.interrupted:
						raise ProcessorInterruptedException("Processor interrupted while iterating through NDJSON file")

					yield json.loads(line)

		else:
			raise NotImplementedError("Cannot iterate through %s file" % path.suffix)

	def iterate_items(self, processor=None, warn_unmappable=True, map_missing="default"):
		"""
		Generate mapped dataset items

		Wrapper for _iterate_items that returns a DatasetItem, which can be
		accessed as a dict returning the original item or (if a mapper is
		available) the mapped item. Mapped or original versions of the item can
		also be accessed via the `original` and `mapped_object` properties of
		the DatasetItem.

		Processors can define a method called `map_item` that can be used to map
		an item from the dataset file before it is processed any further. This is
		slower than storing the data file in the right format to begin with but
		not all data sources allow for easy 'flat' mapping of items, e.g. tweets
		are nested objects when retrieved from the twitter API that are easier
		to store as a JSON file than as a flat CSV file, and it would be a shame
		to throw away that data.

		Note the two parameters warn_unmappable and map_missing. Items can be
		unmappable in that their structure is too different to coerce into a
		neat dictionary of the structure the data source expects. This makes it
		'unmappable' and warn_unmappable determines what happens in this case.
		It can also be of the right structure, but with some fields missing or
		incomplete. map_missing determines what happens in that case. The
		latter is for example possible when importing data via Zeeschuimer,
		which produces unstably-structured data captured from social media
		sites.

		:param BasicProcessor processor:  A reference to the processor
		iterating the dataset.
		:param bool warn_unmappable:  If an item is not mappable, skip the item
		and log a warning
		:param map_missing: Indicates what to do with mapped items for which
		some fields could not be mapped. Defaults to 'empty_str'. Must be one of:
		- 'default': fill missing fields with the default passed by map_item
		- 'abort': raise a MappedItemIncompleteException if a field is missing
		- a callback: replace missing field with the return value of the
		  callback. The MappedItem object is passed to the callback as the
		  first argument and the name of the missing field as the second.
		- a dictionary with a key for each possible missing field: replace missing
		  field with a strategy for that field ('default', 'abort', or a callback)

		:return generator:  A generator that yields DatasetItems
		"""
		unmapped_items = False
		# Collect item_mapper for use with filter
		item_mapper = False
		own_processor = self.get_own_processor()
		if own_processor and own_processor.map_item_method_available(dataset=self):
			item_mapper = True

		# missing field strategy can be for all fields at once, or per field
		# if it is per field, it is a dictionary with field names and their strategy
		# if it is for all fields, it is may be a callback, 'abort', or 'default'
		default_strategy = "default"
		if type(map_missing) is not dict:
			default_strategy = map_missing
			map_missing = {}

		# Loop through items
		for i, item in enumerate(self._iterate_items(processor)):
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

				# check if fields have been marked as 'missing' in the
				# underlying data, and treat according to the chosen strategy
				if mapped_item.get_missing_fields():
					for missing_field in mapped_item.get_missing_fields():
						strategy = map_missing.get(missing_field, default_strategy)

						if callable(strategy):
							# delegate handling to a callback
							mapped_item.data[missing_field] = strategy(mapped_item.data, missing_field)
						elif strategy == "abort":
							# raise an exception to be handled at the processor level
							raise MappedItemIncompleteException(f"Cannot process item, field {missing_field} missing in source data.")
						elif strategy == "default":
							# use whatever was passed to the object constructor
							mapped_item.data[missing_field] = mapped_item.data[missing_field].value
						else:
							raise ValueError("map_missing must be 'abort', 'default', or a callback.")

			else:
				mapped_item = original_item

			# yield a DatasetItem, which is a dict with some special properties
			yield DatasetItem(mapper=item_mapper, original=original_item, mapped_object=mapped_item, **(mapped_item.get_item_data() if type(mapped_item) is MappedItem else mapped_item))

	def get_item_keys(self, processor=None):
		"""
		Get item attribute names

		It can be useful to know what attributes an item in the dataset is
		stored with, e.g. when one wants to produce a new dataset identical
		to the source_dataset one but with extra attributes. This method provides
		these, as a list.

		:param BasicProcessor processor:  A reference to the processor
		asking for the item keys, to pass on to iterate_mapped_items
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

		results_dir_base = results_file.parent
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
			except DataSetException:
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
				self.db.insert("datasets_owners", data={"key": self.key, "name": owner, "role": role}, commit=False, safe=True)

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

	def get_key(self, query, parameters, parent="", time_offset=0):
		"""
		Generate a unique key for this dataset that can be used to identify it

		The key is a hash of a combination of the query string and parameters.
		You never need to call this, really: it's used internally.

		:param str query:  Query string
		:param parameters:  Dataset parameters
		:param parent: Parent dataset's key (if applicable)
		:param time_offset:  Offset to add to the time component of the dataset
		key. This can be used to ensure a unique key even if the parameters and
		timing is otherwise identical to an existing dataset's

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

		# we additionally use the current time as a salt - this should usually
		# ensure a unique key for the dataset. if for some reason there is a
		# hash collision
		param_key["_salt"] = int(time.time()) + time_offset

		parent_key = str(parent) if parent else ""
		plain_key = repr(param_key) + str(query) + parent_key
		hashed_key = hashlib.md5(plain_key.encode("utf-8")).hexdigest()

		if self.db.fetchone("SELECT key FROM datasets WHERE key = %s", (hashed_key,)):
			# key exists, generate a new one
			return self.get_key(query, parameters, parent, time_offset=random.randint(1,10))
		else:
			return hashed_key

	def set_key(self, key):
		"""
		Change dataset key

		In principe, keys should never be changed. But there are rare cases
		where it is useful to do so, in particular when importing a dataset
		from another 4CAT instance; in that case it makes sense to try and
		ensure that the key is the same as it was before. This function sets
		the dataset key and updates any dataset references to it.

		:param str key:  Key to set
		:return str:  Key that was set. If the desired key already exists, the
		original key is kept.
		"""
		key_exists = self.db.fetchone("SELECT * FROM datasets WHERE key = %s", (key,))
		if key_exists or not key:
			return self.key

		old_key = self.key
		self.db.update("datasets", data={"key": key}, where={"key": old_key})

		# update references
		self.db.update("datasets", data={"key_parent": key}, where={"key_parent": old_key})
		self.db.update("datasets_owners", data={"key": key}, where={"key": old_key})
		self.db.update("jobs", data={"remote_id": key}, where={"remote_id": old_key})
		self.db.update("users_favourites", data={"key": key}, where={"key": old_key})

		# for good measure
		self.db.commit()
		self.key = key

		return self.key

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
			except DataSetException:
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

	def get_place_in_queue(self, update=False):
		"""
		Determine dataset's position in queue

		If the dataset is already finished, the position is -1. Else, the
		position is the amount of datasets to be completed before this one will
		be processed. A position of 0 would mean that the dataset is currently
		being executed, or that the backend is not running.

		:param bool update:  Update the queue position from database if True, else return cached value
		:return int:  Queue position
		"""
		if self.is_finished() or not self.data.get("job"):
			self._queue_position = -1
			return self._queue_position
		elif not update and self._queue_position is not None:
			# Use cached value
			return self._queue_position
		else:
			# Collect queue position from database via the job
			try:
				job = Job.get_by_ID(self.data["job"], self.db)
				self._queue_position = job.get_place_in_queue()
			except JobNotFoundException:
				self._queue_position = -1

			return self._queue_position

	def get_own_processor(self):
		"""
		Get the processor class that produced this dataset

		:return:  Processor class, or `None` if not available.
		"""
		processor_type = self.parameters.get("type", self.data.get("type"))
		return backend.all_modules.processors.get(processor_type)

	def get_available_processors(self, user=None, exclude_hidden=False):
		"""
		Get list of processors that may be run for this dataset

		Returns all compatible processors except for those that are already
		queued or finished and have no options. Processors that have been
		run but have options are included so they may be run again with a
		different configuration

		:param str|User|None user:  User to get compatibility for. If set,
		use the user-specific config settings where available.
		:param bool exclude_hidden:  Exclude processors that should be displayed
		in the UI? If `False`, all processors are returned.

		:return dict:  Available processors, `name => properties` mapping
		"""
		if self.available_processors:
			# Update to reflect exclude_hidden parameter which may be different from last call
			# TODO: could children also have been created? Possible bug, but I have not seen anything effected by this
			return {processor_type: processor for processor_type, processor in self.available_processors.items() if not exclude_hidden or not processor.is_hidden}

		processors = self.get_compatible_processors(user=user)

		for analysis in self.children:
			if analysis.type not in processors:
				continue

			if not processors[analysis.type].get_options():
				del processors[analysis.type]
				continue

			if exclude_hidden and processors[analysis.type].is_hidden:
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
				# borrow the database's log handler
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
