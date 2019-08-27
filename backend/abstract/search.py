import shutil
import random
import math

from abc import ABC, abstractmethod

from backend.lib.dataset import DataSet
from backend.abstract.processor import BasicProcessor
from backend.lib.helpers import posts_to_csv, get_software_version


class Search(BasicProcessor, ABC):
	"""
	Process substring queries from the front-end

	Requests are added to the pool as "query" jobs. This class is to be
	extended by data source-specific search classes, which will define the
	abstract methods at the end of this class to tailor the search engine
	to their database layouts.
	"""
	type = "query"
	max_workers = 2

	prefix = ""

	dataset = None

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
		posts = self.search(query_parameters)

		# Write posts to csv and update the DataBase status to finished
		if posts:
			self.dataset.update_status("Writing posts to result file")
			posts_to_csv(posts, results_file)
			self.dataset.update_status("Query finished, results are available.")
		elif posts is not None:
			self.dataset.update_status("Query finished, no results found.")

		num_posts = len(posts) if posts else 0

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
		if query.get("body_match", None) or query.get("subject_match", None):
			mode = "complex"
			posts = self.get_posts_complex(query)
		else:
			mode = "simple"
			posts = self.get_posts_simple(query)

		if not posts:
			return None

		# handle the various search scope options after retrieving initial post
		# list
		self.log.info("Scope: %s" % query.get("search_scope"))
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

			self.dataset.update_status("Fetching all posts in %i threads" % len(qualifying_thread_ids))
			posts = self.fetch_threads(tuple(qualifying_thread_ids))

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
					sample_size = int(query.get("sample_size", 5000))
					random.shuffle(posts)
					return posts[0:sample_size]
				except ValueError:
					pass

		return posts

	@abstractmethod
	def get_posts_simple(self, query):
		pass

	@abstractmethod
	def get_posts_complex(self, query):
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