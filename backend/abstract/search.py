import hashlib
import shutil
import random
import json
import math
import csv
import copy

from pathlib import Path
from abc import ABC, abstractmethod

import config

from common.lib.dataset import DataSet
from backend.abstract.processor import BasicProcessor
from common.lib.helpers import strip_tags, dict_search_and_update
from common.lib.exceptions import WorkerInterruptedException, ProcessorInterruptedException


class Search(BasicProcessor, ABC):
	"""
	Process substring queries from the front-end

	Requests are added to the pool as "query" jobs. This class is to be
	extended by data source-specific search classes, which will define the
	abstract methods at the end of this class to tailor the search engine
	to their database layouts.
	"""
	type = "query"
	max_workers = 1

	prefix = ""

	# Columns to return in csv
	# Mandatory columns: ['thread_id', 'body', 'subject', 'timestamp']
	return_cols = ['thread_id', 'body', 'subject', 'timestamp']

	# not available as a processor for existing datasets
	accepts = [None]

	def process(self):
		"""
		Run 4CAT search query

		Gets query details, passes them on to the object's search method, and
		writes the results to a CSV file. If that all went well, the query and
		job are marked as finished.
		"""

		query_parameters = self.dataset.get_parameters()
		results_file = self.dataset.get_results_path()

		self.log.info("Querying: %s" % str(query_parameters))

		# Execute the relevant query (string-based, random, countryflag-based)
		try:
			posts = self.search(query_parameters)
		except WorkerInterruptedException:
			raise ProcessorInterruptedException("Interrupted while collecting data, trying again later.")

		# Write posts to csv and update the DataBase status to finished
		num_posts = 0
		if posts:
			self.dataset.update_status("Writing posts to result file")
			if not hasattr(self, "extension") or self.extension == "csv":
				num_posts = self.items_to_csv(posts, results_file)
			elif self.extension == "ndjson":
				num_posts = self.items_to_ndjson(posts, results_file)
			else:
				raise NotImplementedError("Datasource query cannot be saved as %s file" % self.extension)

			self.dataset.update_status("Query finished, results are available.")
		elif posts is not None:
			self.dataset.update_status("Query finished, no results found.")

		# queue predefined post-processors
		if num_posts > 0 and query_parameters.get("next", []):
			for next in query_parameters.get("next"):
				next_parameters = next.get("parameters", {})
				next_type = next.get("type", "")
				available_processors = self.dataset.get_available_processors()

				# run it only if the post-processor is actually available for this query
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

		self.dataset.finish(num_rows=num_posts)

	def search(self, query):
		"""
		Search for items matching the given query

		The real work is done by the get_posts() method of the descending
		class. This method just provides some scaffolding and post-processing
		of results via `after_search()`, if it is defined.

		:param dict query:  Query parameters
		:return:  Iterable of matching items, or None if there are no results.
		"""
		posts = self.get_items(query)

		if not posts:
			return None

		# search workers may define an 'after_search' hook that is called after
		# the query is first completed
		if hasattr(self, "after_search") and callable(self.after_search):
			posts = self.after_search(posts)

		return posts

	@abstractmethod
	def get_items(self, query):
		"""
		Method to fetch items with for a given query

		To be implemented by descending classes!
		"""
		pass

	def items_to_csv(self, results, filepath):
		"""
		Takes a dictionary of results, converts it to a csv, and writes it to the
		given location. This is mostly a generic dictionary-to-CSV processor but
		some specific processing is done on the "body" key to strip HTML from it,
		and a human-readable timestamp is provided next to the UNIX timestamp.

		:param results:			List of dict rows from data source.
		:param filepath:		Filepath for the resulting csv

		:return int:  Amount of posts that were processed

		"""
		if not filepath:
			raise ResourceWarning("No result file for query")

		# write the dictionary to a csv
		if not isinstance(filepath, Path):
			filepath = Path(filepath)

		# cache hashed author names, so the hashing function (which is
		# relatively expensive) is not run too often
		pseudonymise_author = bool(self.parameters.get("pseudonymise", None))
		hash_cache = {}

		# prepare hasher (which we may or may not need)
		# we use BLAKE2	for its (so far!) resistance against cryptanalysis and
		# speed, since we will potentially need to calculate a large amount of
		# hashes
		hasher = hashlib.blake2b(digest_size=24)
		hasher.update(str(config.ANONYMISATION_SALT).encode("utf-8"))

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
					check_cashe = CheckCashe(hash_cache, hasher)
					author_fields = [field for field in row.keys() if "author" in field]
					for author_field in author_fields:
						row[author_field] = check_cashe.update_cache(row[author_field])
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

		# cache hashed author names, so the hashing function (which is
		# relatively expensive) is not run too often
		pseudonymise_author = bool(self.parameters.get("pseudonymise", None))
		if pseudonymise_author:
			hash_cache = {}
			hasher = hashlib.blake2b(digest_size=24)
			hasher.update(str(config.ANONYMISATION_SALT).encode("utf-8"))
			check_cashe = CheckCashe(hash_cache, hasher)

		processed = 0
		with filepath.open("w", encoding="utf-8", newline="") as outfile:
			for item in items:
				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while writing results to file")

				# replace author column with salted hash of the author name, if
				# pseudonymisation is enabled
				if pseudonymise_author:
					item = dict_search_and_update(item, ['author'], check_cashe.update_cache)

				outfile.write(json.dumps(item) + "\n")
				processed += 1

		return processed

class CheckCashe():
	"""
	Handler for the hasher
	"""
	def __init__(self, hash_cache, hasher):
		self.hash_cache = hash_cache
		self.hasher = hasher

	def update_cache(self, value):
		"""
		Checks the hash_cache to see if the value has been cached previously,
		updates the hash_cache if needed, and returns the hashed value.
		"""
		# value = str(value)
		if value not in self.hash_cache:
			author_hasher = self.hasher.copy()
			author_hasher.update(str(value).encode("utf-8"))
			self.hash_cache[value] = author_hasher.hexdigest()
			del author_hasher
		return self.hash_cache[value]


class SearchWithScope(Search, ABC):
	"""
	Search class with more complex search pathways

	Some datasources may afford more complex search modes besides simply
	returning all items matching a given set of parameters. In particular,
	they may allow for expanding the search scope to the thread in which a
	given matching item occurs. This subclass allows for the following
	additional search modes:

	- All posts in a thread containing a matching post
	- All posts in a thread containing at least x% matching posts
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
			posts = self.get_items_simple(query)
		else:
			posts = self.get_items_complex(query)

		if not posts:
			return None

		# handle the various search scope options after retrieving initial post
		# list
		if query.get("search_scope", None) == "dense-threads":
			# dense threads - all posts in all threads in which the requested
			# proportion of posts matches
			# first, get amount of posts for all threads in which matching
			# posts occur and that are long enough
			thread_ids = tuple([post["thread_id"] for post in posts])
			self.dataset.update_status("Retrieving thread metadata for %i threads" % len(thread_ids))
			try:
				min_length = int(query.get("scope_length", 30))
			except ValueError:
				min_length = 30

			thread_sizes = self.get_thread_sizes(thread_ids, min_length)

			# determine how many matching posts occur per thread in the initial
			# data set
			posts_per_thread = {}
			for post in posts:
				if post["thread_id"] not in posts_per_thread:
					posts_per_thread[post["thread_id"]] = 0

				posts_per_thread[post["thread_id"]] += 1

			# keep all thread IDs where that amount is more than the requested
			# density
			qualifying_thread_ids = set()

			self.dataset.update_status("Filtering dense threads")
			try:
				percentage = int(query.get("scope_density")) / 100
			except (ValueError, TypeError):
				percentage = 0.15

			for thread_id in posts_per_thread:
				if thread_id not in thread_sizes:
					# thread not long enough
					continue
				required_posts = math.ceil(percentage * thread_sizes[thread_id])
				if posts_per_thread[thread_id] >= required_posts:
					qualifying_thread_ids.add(thread_id)

			if len(qualifying_thread_ids) > 25000:
				self.dataset.update_status(
					"Too many matching threads (%i) to get full thread data for, aborting. Please try again with a narrower query." % len(
						qualifying_thread_ids))
				return None

			if qualifying_thread_ids:
				self.dataset.update_status("Fetching all posts in %i threads" % len(qualifying_thread_ids))
				posts = self.fetch_threads(tuple(qualifying_thread_ids))
			else:
				self.dataset.update_status("No threads matched the full thread search parameters.")
				return None

		elif query.get("search_scope", None) == "full-threads":
			# get all post in threads containing at least one matching post
			thread_ids = tuple(set([post["thread_id"] for post in posts]))
			if len(thread_ids) > 25000:
				self.dataset.update_status(
					"Too many matching threads (%i) to get full thread data for, aborting. Please try again with a narrower query." % len(
						thread_ids))
				return None

			self.dataset.update_status("Retrieving all posts from %i threads" % len(thread_ids))
			posts = self.fetch_threads(thread_ids)

		elif mode == "complex":
			# create a random sample subset of all posts if requested. for
			# complex queries, this can usually only be done at this point;
			# for simple queries, this is handled in get_posts_simple
			if query.get("search_scope", None) == "random-sample":
				try:
					self.dataset.update_status("Creating random sample")
					sample_size = int(query.get("sample_size", 5000))
					posts = list(posts)
					random.shuffle(posts)
					return posts[0:sample_size]
				except ValueError:
					pass

		# search workers may define an 'after_search' hook that is called after
		# the query is first completed
		if hasattr(self, "after_search") and callable(self.after_search):
			posts = self.after_search(posts)

		return posts

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
		pass

	@abstractmethod
	def get_items_complex(self, query):
		pass

	@abstractmethod
	def fetch_posts(self, post_ids, where=None, replacements=None):
		pass

	@abstractmethod
	def fetch_threads(self, thread_ids):
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
