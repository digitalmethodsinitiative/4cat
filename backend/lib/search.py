import hashlib
import secrets
import shutil
import random
import json
import math
import csv

from pathlib import Path
from abc import ABC, abstractmethod

from common.config_manager import config
from common.lib.dataset import DataSet
from backend.lib.processor import BasicProcessor
from common.lib.helpers import strip_tags, dict_search_and_update, remove_nuls, HashCache
from common.lib.exceptions import WorkerInterruptedException, ProcessorInterruptedException, MapItemException


class Search(BasicProcessor, ABC):
	"""
	Process search queries from the front-end

	This class can be descended from to define a 'search worker', which
	collects items from a given data source to create a dataset according to
	parameters provided by the user via the web interface.

	Each data source defines a search worker that contains code to interface
	with e.g. an API or a database server. The search worker also contains a
	definition of the parameters that can be configured by the user, via the
	`options` attribute and/or the `get_options()` class method.
	"""
	#: Search worker identifier - should end with 'search' for
	#: backwards-compatibility reasons. For example, `instagram-search`.
	type = "abstract-search"

	#: Amount of workers of this type that can run in parallel. Be careful with
	#: this, because values higher than 1 will mean that e.g. API rate limits
	#: are easily violated.
	max_workers = 1

	#: This attribute is only used by search workers that collect data from a
	#: local database, to determine the name of the table to collect the data
	#: from. If this is `4chan`, for example, items are read from
	#: `posts_4chan`.
	prefix = ""

	# Columns to return in csv
	# Mandatory columns: ['thread_id', 'body', 'subject', 'timestamp']
	return_cols = ['thread_id', 'body', 'subject', 'timestamp']

	flawless = 0

	def process(self):
		"""
		Create 4CAT dataset from a data source

		Gets query details, passes them on to the object's search method, and
		writes the results to a file. If that all went well, the query and job
		are marked as finished.
		"""

		query_parameters = self.dataset.get_parameters()
		results_file = self.dataset.get_results_path()

		self.log.info("Querying: %s" % str({k: v for k, v in query_parameters.items() if not self.get_options().get(k, {}).get("sensitive", False)}))

		# Execute the relevant query (string-based, random, countryflag-based)
		try:
			if query_parameters.get("file"):
				items = self.import_from_file(query_parameters.get("file"))
			else:
				items = self.search(query_parameters)

		except WorkerInterruptedException:
			raise ProcessorInterruptedException("Interrupted while collecting data, trying again later.")

		# Write items to file and update the DataBase status to finished
		num_items = 0
		if items:
			self.dataset.update_status("Writing collected data to dataset file")
			if results_file.suffix == ".ndjson":
				num_items = self.items_to_ndjson(items, results_file)
			elif results_file.suffix == ".csv":
				num_items = self.items_to_csv(items, results_file)
			else:
				raise NotImplementedError("Datasource query cannot be saved as %s file" % results_file.suffix)

			self.dataset.update_status("Query finished, results are available.")
		elif items is not None:
			self.dataset.update_status("Query finished, no results found.")

		# queue predefined processors
		if num_items > 0 and query_parameters.get("next", []):
			for next in query_parameters.get("next"):
				next_parameters = next.get("parameters", {})
				next_type = next.get("type", "")
				available_processors = self.dataset.get_available_processors(user=self.dataset.creator)

				# run it only if the processor is actually available for this query
				if next_type in available_processors:
					next_analysis = DataSet(parameters=next_parameters, type=next_type, db=self.db,
											parent=self.dataset.key,
											extension=available_processors[next_type]["extension"])
					self.queue.add_job(next_type, remote_id=next_analysis.key)

		# see if we need to register the result somewhere
		if query_parameters.get("copy_to", None):
			# copy the results to an arbitrary place that was passed
			if self.dataset.get_results_path().exists():
				# but only if we actually have something to copy
				shutil.copyfile(str(self.dataset.get_results_path()), query_parameters.get("copy_to"))
			else:
				# if copy_to was passed, that means it's important that this
				# file exists somewhere, so we create it as an empty file
				with open(query_parameters.get("copy_to"), "w") as empty_file:
					empty_file.write("")
		if self.flawless == 0:
			self.dataset.finish(num_rows=num_items)
		else:
			self.dataset.update_status(f"Unexpected data format for {self.flawless} items. All data can be downloaded, but only data with expected format will be available to 4CAT processors; check logs for details", is_final=True)
			self.dataset.finish(num_rows=num_items)

	def search(self, query):
		"""
		Search for items matching the given query

		The real work is done by the get_items() method of the descending
		class. This method just provides some scaffolding and processing
		of results via `after_search()`, if it is defined.

		:param dict query:  Query parameters
		:return:  Iterable of matching items, or None if there are no results.
		"""
		items = self.get_items(query)

		if not items:
			return None

		# search workers may define an 'after_search' hook that is called after
		# the query is first completed
		if hasattr(self, "after_search") and callable(self.after_search):
			items = self.after_search(items)

		return items

	@abstractmethod
	def get_items(self, query):
		"""
		Method to fetch items with for a given query

		To be implemented by descending classes!

		:param dict query:  Query parameters
		:return Generator:  A generator or iterable that returns items
		  collected according to the provided parameters.
		"""
		pass

	def import_from_file(self, path):
		"""
		Import items from an external file

		By default, this reads a file and parses each line as JSON, returning
		the parsed object as an item. This works for NDJSON files. Data sources
		that require importing from other or multiple file types can overwrite
		this method.

		This method has a generic implementation, but in most cases would be
		redefined in descending classes to account for nuances in incoming data
		for a given data source.

		The file is considered disposable and deleted after importing.

		:param str path:  Path to read from
		:return Generator:  Yields all items in the file, item for item.
		"""
		if type(path) is not Path:
			path = Path(path)
		if not path.exists():
			return []

		# Check if processor and dataset can use map_item
		check_map_item = self.map_item_method_available(dataset=self.dataset)
		if not check_map_item:
			self.log.warning(
				f"Processor {self.type} importing item without map_item method for Dataset {self.dataset.type} - {self.dataset.key}")

		with path.open(encoding="utf-8") as infile:
			unmapped_items = False
			for i, line in enumerate(infile):
				if self.interrupted:
					raise WorkerInterruptedException()

				# remove NUL bytes here because they trip up a lot of other
				# things
				# also include import metadata in item
				item = json.loads(line.replace("\0", ""))
				new_item = {
					**item["data"],
					"__import_meta": {k: v for k, v in item.items() if k != "data"}
				}
				# Check map item here!
				if check_map_item:
					try:
						self.get_mapped_item(new_item)
					except MapItemException as e:
						# NOTE: we still yield the unmappable item; perhaps we need to update a processor's map_item method to account for this new item
						self.flawless += 1
						self.dataset.warn_unmappable_item(item_count=i, processor=self, error_message=e, warn_admins=unmapped_items is False)
						unmapped_items = True

				yield new_item

		path.unlink()
		self.dataset.delete_parameter("file")

	def items_to_csv(self, results, filepath):
		"""
		Takes a dictionary of results, converts it to a csv, and writes it to the
		given location. This is mostly a generic dictionary-to-CSV processor but
		some specific processing is done on the "body" key to strip HTML from it,
		and a human-readable timestamp is provided next to the UNIX timestamp.

		:param Iterable results:  List of dict rows from data source.
		:param Path filepath:  Filepath for the resulting csv

		:return int:  Amount of items that were processed

		"""
		if not filepath:
			raise ResourceWarning("No result file for query")

		# write the dictionary to a csv
		if not isinstance(filepath, Path):
			filepath = Path(filepath)

		# cache hashed author names, so the hashing function (which is
		# relatively expensive) is not run too often
		pseudonymise_author = self.parameters.get("pseudonymise", None) == "pseudonymise"
		anonymise_author = self.parameters.get("pseudonymise", None) == "anonymise"

		# prepare hasher (which we may or may not need)
		# we use BLAKE2	for its (so far!) resistance against cryptanalysis and
		# speed, since we will potentially need to calculate a large amount of
		# hashes
		salt = secrets.token_bytes(16)
		hasher = hashlib.blake2b(digest_size=24, salt=salt)
		hash_cache = HashCache(hasher)

		processed = 0
		header_written = False
		with filepath.open("w", encoding="utf-8") as csvfile:
			# Parsing: remove the HTML tags, but keep the <br> as a newline
			# Takes around 1.5 times longer
			for row in results:
				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while writing results to file")

				if not header_written:
					fieldnames = list(row.keys())
					fieldnames.append("unix_timestamp")
					writer = csv.DictWriter(csvfile, fieldnames=fieldnames, lineterminator='\n')
					writer.writeheader()
					header_written = True

				processed += 1

				# Create human dates from timestamp
				from datetime import datetime, timezone

				if "timestamp" in row:
					# Data sources should have "timestamp" as a unix epoch integer,
					# but do some conversion if this is not the case.
					timestamp = row["timestamp"]
					if not isinstance(timestamp, int):
						if isinstance(timestamp,
									  str) and "-" not in timestamp:  # String representation of epoch timestamp
							timestamp = int(timestamp)
						elif isinstance(timestamp, str) and "-" in timestamp:  # Date string
							try:
								timestamp = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").replace(
									tzinfo=timezone.utc).timestamp()
							except ValueError:
								timestamp = "undefined"
						else:
							timestamp = "undefined"

					# Add a human-readable date format as well, if we have a valid timestamp.
					row["unix_timestamp"] = timestamp
					if timestamp != "undefined":
						row["timestamp"] = datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
					else:
						row["timestamp"] = timestamp
				else:
					row["timestamp"] = "undefined"

				# Parse html to text
				if row["body"]:
					row["body"] = strip_tags(row["body"])

				# replace author column with salted hash of the author name, if
				# pseudonymisation is enabled
				if pseudonymise_author:
					author_fields = [field for field in row.keys() if field.startswith("author")]
					for author_field in author_fields:
						row[author_field] = hash_cache.update_cache(row[author_field])

				# or remove data altogether, if it's anonymisation instead
				elif anonymise_author:
					for field in row.keys():
						if field.startswith("author"):
							row[field] = "REDACTED"

				row = remove_nuls(row)
				writer.writerow(row)

		return processed

	def items_to_ndjson(self, items, filepath):
		"""
		Save retrieved items as an ndjson file

		NDJSON is a file with one valid JSON value per line, in this case each
		of these JSON values represents a retrieved item. This is useful if the
		retrieved data cannot easily be completely stored as a flat CSV file
		and we want to leave the choice of how to flatten it to the user. Note
		that no conversion (e.g. html stripping or pseudonymisation) is done
		here - the items are saved as-is.

		:param Iterator items:  Items to save
		:param Path filepath:  Location to save results file
		"""
		if not filepath:
			raise ResourceWarning("No valid results path supplied")

		# figure out if we need to filter the data somehow
		hash_cache = None
		if self.parameters.get("pseudonymise") == "pseudonymise":
			# cache hashed author names, so the hashing function (which is
			# relatively expensive) is not run too often
			hasher = hashlib.blake2b(digest_size=24)
			hasher.update(str(config.get('ANONYMISATION_SALT')).encode("utf-8"))
			hash_cache = HashCache(hasher)

		processed = 0
		with filepath.open("w", encoding="utf-8", newline="") as outfile:
			for item in items:
				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while writing results to file")

				# if pseudo/anonymising, filter data recursively
				if self.parameters.get("pseudonymise") == "pseudonymise":
					item = dict_search_and_update(item, ["author*"], hash_cache.update_cache)
				elif self.parameters.get("anonymise") == "anonymise":
					item = dict_search_and_update(item, ["author*"], lambda v: "REDACTED")

				outfile.write(json.dumps(item) + "\n")
				processed += 1

		return processed


class SearchWithScope(Search, ABC):
	"""
	Search class with more complex search pathways

	Some datasources may afford more complex search modes besides simply
	returning all items matching a given set of parameters. In particular,
	they may allow for expanding the search scope to the thread in which a
	given matching item occurs. This subclass allows for the following
	additional search modes:

	- All items in a thread containing a matching item
	- All items in a thread containing at least x% matching items
	"""

	def search(self, query):
		"""
		Complex search

		Allows for two separate search pathways, one of which is chosen based
		on the search query. Additionally, extra items are added to the results
		if a wider search scope is requested.

		:param dict query:  Query parameters
		:return:  Matching items, as iterable, or None if no items match.
		"""
		mode = self.get_search_mode(query)

		if mode == "simple":
			items = self.get_items_simple(query)
		else:
			items = self.get_items_complex(query)

		if not items:
			return None

		# handle the various search scope options after retrieving initial item
		# list
		if query.get("search_scope", None) == "dense-threads":
			# dense threads - all items in all threads in which the requested
			# proportion of items matches
			# first, get amount of items for all threads in which matching
			# items occur and that are long enough
			thread_ids = tuple([post["thread_id"] for post in items])
			self.dataset.update_status("Retrieving thread metadata for %i threads" % len(thread_ids))
			try:
				min_length = int(query.get("scope_length", 30))
			except ValueError:
				min_length = 30

			thread_sizes = self.get_thread_sizes(thread_ids, min_length)

			# determine how many matching items occur per thread in the initial
			# data set
			items_per_thread = {}
			for item in items:
				if item["thread_id"] not in items_per_thread:
					items_per_thread[item["thread_id"]] = 0

				items_per_thread[item["thread_id"]] += 1

			# keep all thread IDs where that amount is more than the requested
			# density
			qualifying_thread_ids = set()

			self.dataset.update_status("Filtering dense threads")
			try:
				percentage = int(query.get("scope_density")) / 100
			except (ValueError, TypeError):
				percentage = 0.15

			for thread_id in items_per_thread:
				if thread_id not in thread_sizes:
					# thread not long enough
					continue
				required_items = math.ceil(percentage * thread_sizes[thread_id])
				if items_per_thread[thread_id] >= required_items:
					qualifying_thread_ids.add(thread_id)

			if len(qualifying_thread_ids) > 25000:
				self.dataset.update_status(
					"Too many matching threads (%i) to get full thread data for, aborting. Please try again with a narrower query." % len(
						qualifying_thread_ids))
				return None

			if qualifying_thread_ids:
				self.dataset.update_status("Fetching all items in %i threads" % len(qualifying_thread_ids))
				items = self.fetch_threads(tuple(qualifying_thread_ids))
			else:
				self.dataset.update_status("No threads matched the full thread search parameters.")
				return None

		elif query.get("search_scope", None) == "full-threads":
			# get all items in threads containing at least one matching item
			thread_ids = tuple(set([item["thread_id"] for item in items]))
			if len(thread_ids) > 25000:
				self.dataset.update_status(
					"Too many matching threads (%i) to get full thread data for, aborting. Please try again with a narrower query." % len(
						thread_ids))
				return None

			self.dataset.update_status("Retrieving all items from %i threads" % len(thread_ids))
			items = self.fetch_threads(thread_ids)

		elif mode == "complex":
			# create a random sample subset of all items if requested. for
			# complex queries, this can usually only be done at this point;
			# for simple queries, this is handled in get_items_simple
			if query.get("search_scope", None) == "random-sample":
				try:
					self.dataset.update_status("Creating random sample")
					sample_size = int(query.get("sample_size", 5000))
					items = list(items)
					random.shuffle(items)
					return items[0:sample_size]
				except ValueError:
					pass

		# search workers may define an 'after_search' hook that is called after
		# the query is first completed
		if hasattr(self, "after_search") and callable(self.after_search):
			items = self.after_search(items)

		return items

	def get_items(self, query):
		"""
		Not available in this subclass
		"""
		raise NotImplementedError("Cannot use get_items() directly in SearchWithScope")

	def get_search_mode(self, query):
		"""
		Determine what search mode to use

		Can be overridden by child classes!

		:param dict query:  Query parameters
		:return str:  'simple' or 'complex'
		"""
		if query.get("body_match", None) or query.get("subject_match", None):
			mode = "complex"
		else:
			mode = "simple"

		return mode

	@abstractmethod
	def get_items_simple(self, query):
		"""
		Get items via the simple pathway

		If `get_search_mode()` returned `"simple"`, this method is used to
		retrieve items. What this method does exactly is up to the descending
		class.

		:param dict query:  Query parameters
		:return Iterable:  Items that match the parameters
		"""
		pass

	@abstractmethod
	def get_items_complex(self, query):
		"""
		Get items via the complex pathway

		If `get_search_mode()` returned `"complex"`, this method is used to
		retrieve items. What this method does exactly is up to the descending
		class.

		:param dict query:  Query parameters
		:return Iterable:  Items that match the parameters
		"""
		pass

	@abstractmethod
	def fetch_posts(self, post_ids, where=None, replacements=None):
		"""
		Get items for given IDs

		:param Iterable post_ids:  Post IDs to e.g. match against a database
		:param where:  Deprecated, do not use
		:param replacements:  Deprecated, do not use
		:return Iterable[dict]:  Post objects
		"""
		pass

	@abstractmethod
	def fetch_threads(self, thread_ids):
		"""
		Get items for given thread IDs

		:param Iterable thread_ids:  Thread IDs to e.g. match against a database
		:return Iterable[dict]:  Post objects
		"""
		pass

	@abstractmethod
	def get_thread_sizes(self, thread_ids, min_length):
		"""
		Get thread lengths for all threads

		:param tuple thread_ids:  List of thread IDs to fetch lengths for
		:param int min_length:  Min length for a thread to be included in the
		results
		:return dict:  Threads sizes, with thread IDs as keys
		"""
		pass
