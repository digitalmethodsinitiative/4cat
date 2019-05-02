import requests
import abc
import re

from backend.lib.query import DataSet
from backend.lib.helpers import posts_to_csv
from backend.abstract.string_query import StringQuery


class SearchReddit(StringQuery):
	"""
	Process substring queries from the front-end

	Requests are added to the pool as "query" jobs. This class is to be
	extended by platform-specific search classes, which will define the
	abstract methods at the end of this class to tailor the search engine
	to their database layouts.
	"""

	type = "reddit-search"
	max_workers = 1

	query = None

	def work(self):
		"""
		Run 4CAT search query

		Gets query details, passes them on to the object's search method, and
		writes the results to a CSV file. If that all went well, the query and
		job are marked as finished.
		"""
		# Setup connections and get parameters
		key = self.job.data["remote_id"]
		try:
			self.query = DataSet(key=key, db=self.db)
		except TypeError:
			self.log.info("Query job %s refers to non-existent query, finishing." % key)
			self.job.finish()
			return

		if self.query.is_finished():
			self.log.info("Worker started for query %s, but query is already finished" % key)
			self.job.finish()
			return

		query_parameters = self.query.get_parameters()
		results_file = self.query.get_results_path()
		results_file = results_file.replace("*", "")

		# Execute the relevant query (string-based, random, countryflag-based)
		if "random_amount" in query_parameters and query_parameters["random_amount"]:
			posts = self.execute_random_query(query_parameters)
		elif "country_flag" in query_parameters and query_parameters["country_flag"] != "all":
			posts = self.execute_country_query(query_parameters)
		else:
			posts = self.execute_string_query(query_parameters)

		# Write posts to csv and update the DataBase status to finished
		if posts:
			# self.query.update_status("Writing posts to result file")
			posts_to_csv(posts, results_file)
		# self.query.update_status("Query finished, results are available.")
		elif posts is not None:
			self.query.update_status("Query finished, no results found.")

		num_posts = len(posts) if posts else 0
		self.query.finish(num_rows=num_posts)
		self.job.finish()

	def execute_string_query(self, query):
		"""
		Execute a query; get post data for given parameters

		This handles general search - anything that does not involve dense
		threads (those are handled by get_dense_threads()). First, Sphinx is
		queries with the search parameters to get the relevant post IDs; then
		the PostgreSQL is queried to return all posts for the found IDs, as
		well as (optionally) all other posts in the threads those posts were in.

		:param dict query:  Query parameters, as part of the DataSet object
		:return list:  Posts, sorted by thread and post ID, in ascending order
		"""

		# first, build the sphinx query
		post_parameters = {
			"sort": "asc",
			"sort_type": "created_utc",
			"size": 500,
			"metadata": True
		}

		if query["min_date"]:
			post_parameters["after"] = int(query["min_date"])

		if query["max_date"]:
			post_parameters["before"] = int(query["max_date"])

		if query["board"] and query["board"] != "*":
			post_parameters["subreddit"] = query["board"]

		# escape / since it's a special character for Sphinx
		if query["body_query"]:
			post_parameters["q"] = query["body_query"]
		else:
			post_parameters["q"] = ""

		# set up query
		total_posts = 0
		return_posts = []

		# searching by subject is a little complicated in Reddit but we do it
		# by first searching for threads, then storing the comment IDs for that
		# thread, and next querying all comment IDs found this way.
		if query["subject_query"]:
			chunked_search = True
			chunked_index = 0

			# we need this to check submission URLs (maybe don't filter?)
			image_match = re.compile(r"\.(jpg|jpeg|png|gif|webm|mp4)$", flags=re.IGNORECASE)

			submission_parameters = post_parameters.copy()
			submission_parameters["selftext"] = submission_parameters["q"]

			if query["subject_query"]:
				submission_parameters["title"] = query["subject_query"]

			# this is where we store our progress
			thread_ids = []
			total_threads = 0
			seen_threads = set()

			while True:
				response = requests.get("https://api.pushshift.io/reddit/submission/search", params=post_parameters)

				# if this fails, too much is wrong to continue
				if response.status_code != 200:
					self.query.update_status(
						"HTTP Status code %i while receiving thread data from Pushshift API. Not all posts are saved." % (
							response.status_code))
					return None

				threads = response.json()["data"]

				# this is not the end of the world, but warrants a warning
				if len(threads) == 0:
					break

				# store comment IDs for a thread, and also add the OP to the
				# return list. This means all OPs will come before all comments
				# but we can sort later if that turns out to be a problem
				for thread in threads:
					if thread["id"] not in seen_threads:
						seen_threads.add(thread["id"])
						return_posts.append({
							"thread_id": thread["id"],
							"id": thread["id"],
							"timestamp": thread["created_utc"],
							"body": thread.get("selftext", ""),
							"subject": thread["title"],
							"author": thread["author"],
							"image_file": thread["url"] if image_match.search(thread["url"]) else "",
							"image_md5": "",
							"country_code": "",
							"country_name": "",
							"parent": "",
							"score": thread["score"]
						})
						post_parameters["after"] = thread["created_utc"]
						total_threads += 1

				# update status
				self.query.update_status("Retrieved %i threads via Pushshift API." % total_threads)

			# okay, we have thread IDs, now find out what comments we need
			# we use 500-ID chunks here since the comment search returns
			# 500 results at most
			chunks = []
			chunk = []
			for thread_id in thread_ids:
				response = requests.get("https://api.pushshift.io/reddit/submission/comment_ids/%s" % thread_id)

				# we can continue if this is the case but some posts will be missing
				if response.status_code != 200:
					self.query.update_status(
						"HTTP Status code %i while receiving thread comment IDs from Pushshift API. Not all posts are saved." % (
							response.status_code))
					continue

				# divide the results in 500-ID chunks
				comment_ids = response.content["data"]
				for comment_id in comment_ids:
					if len(chunk) == 500:
						chunks.append(chunk)
						chunk = []

					chunk.append(comment_id)
				chunks.append(chunk)

		else:
			# non-chunked search, if we're not searching by thread
			chunked_search = False
			chunks = []
			chunked_index = 0

		# okay, search the pushshift API for posts
		seen_posts = set()
		while True:
			# chunked search: search within the given IDs only
			if chunked_search:
				post_parameters["ids"] = ",".join(chunks[chunked_index])
				chunked_index += 1

			response = requests.get("https://api.pushshift.io/reddit/comment/search", params=post_parameters)

			# this is bad - return what we have so far, but also warn
			if response.status_code != 200:
				self.query.update_status(
					"HTTP Status code %i while receiving post data from Pushshift API. Not all posts are saved." % (
						response.status_code))
				break

			# if we're not searching by chunks, we know exactly how much to
			# expect, so check if that's all good
			posts = response.json()["data"]
			if len(posts) == 0 and not chunked_search:
				break

			# store post data
			for post in posts:
				if post["id"] not in seen_posts:
					seen_posts.add(post["id"])
					return_posts.append({
						"thread_id": post["link_id"].split("_")[1],
						"id": post["id"],
						"timestamp": post["created_utc"],
						"body": post["body"],
						"subject": "",
						"author": post["author"],
						"image_file": "",
						"image_md5": "",
						"country_code": "",
						"country_name": "",
						"parent": post["parent_id"],
						"score": post["score"]
					})
					if not chunked_search:
						post_parameters["after"] = post["created_utc"]
					total_posts += 1

			# update: if we're searching by chunk, we don't know how much to
			# expect, but otherwise we do
			self.query.update_status("Found %i posts via Pushshift API..." % total_posts)

		# and done!
		return return_posts

	def execute_random_query(self, query):
		"""
		Execute a query; get post data for given parameters

		This handles general search - anything that does not involve dense
		threads (those are handled by get_dense_threads()). First, Sphinx is
		queries with the search parameters to get the relevant post IDs; then
		the PostgreSQL is queried to return all posts for the found IDs, as
		well as (optionally) all other posts in the threads those posts were in.

		:param dict query:  Query parameters, as part of the DataSet object
		:return list:  Posts, sorted by thread and post ID, in ascending order
		"""

		self.query.update_status("Random sample queries are not supported for Reddit.")
		return None

	def execute_country_query(self, query):
		"""
		Get posts with a country flag

		:param str country: Country to filter on
		:return list: filtered list of post ids
		"""

		self.query.update_status("Country queries are not supported for Reddit.")
		return None

	def filter_dense(self, thread_ids, keyword, percentage, length):
		"""
		Filter posts for dense threads.
		Dense threads are threads that contain a keyword more than
		a given amount of times. This takes a post array as returned by
		`execute_string_query()` and filters it so that only posts in threads in which
		the keyword appears more than a given threshold's amount of times
		remain.

		:param list thread_ids:  Threads to filter, result of `execute_string_query()`
		:param string keyword:  Keyword that posts will be matched against
		:param float percentage:  How many posts in the thread need to qualify
		:param int length:  How long a thread needs to be to qualify
		:return list:  Filtered list of posts
		"""

		self.query.update_status("Dense thread queries are not supported for Reddit.")
		return None

	def filter_dense_country(self, thread_ids, country, percentage):
		"""
		Filter posts for dense country threads.
		Dense country threads are threads that contain a country flag more than
        a given amount of times. This takes a post array as returned by
        `execute_string_query()` and filters it so that only posts in threads in which
        the country flag appears more than a given threshold's amount of times
        remain.

		:param list thread_ids:  Threads to filter, result of `execute_country_query()`
		:param string country: Country that posts will be matched against
		:param float percentage:  How many posts in the thread need to qualify
		:return list:  Filtered list of posts
		"""

		self.query.update_status("Country queries are not supported for Reddit.")
		return None

	def fetch_posts(self, post_ids):
		pass

	def fetch_threads(self, thread_ids):
		pass

	def fetch_sphinx(self, where, replacements):
		pass
