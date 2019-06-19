import requests
import abc
import re

from backend.lib.dataset import DataSet
from backend.lib.helpers import posts_to_csv
from backend.abstract.string_query import StringQuery


class SearchReddit(StringQuery):
	"""
	Process substring queries from the front-end

	Requests are added to the pool as "query" jobs. This class is to be
	extended by datasource-specific search classes, which will define the
	abstract methods at the end of this class to tailor the search engine
	to their database layouts.
	"""

	type = "reddit-search"
	max_workers = 1
	max_retries = 3

	query = None

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

		# we need this to check thread URLs (but maybe don't filter?)
		image_match = re.compile(r"\.(jpg|jpeg|png|gif|webm|mp4)$", flags=re.IGNORECASE)

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
		max_retries = 3

		# first, search for threads - this is a separate endpoint from comments
		submission_parameters = post_parameters.copy()
		submission_parameters["selftext"] = submission_parameters["q"]

		if query["subject_query"]:
			submission_parameters["title"] = query["subject_query"]

		# Check whether only OPs linking to certain URLs should be retreived
		if query.get("url", None):
			urls = []
			domains = []

			if "," in query["url"]:
				urls_input = query["url"].split(",")
			elif "|" in query["url"]:
				urls_input = query["url"].split("|")
			else:
				urls_input = [query["url"]]

			# Input strings
			for url in urls_input:

				# Some cleaning
				url = url.strip()

				url_clean = url.replace("http://","")
				url_clean = url.replace("https://","")
				url_clean = url.replace("www.","")

				# Store urls or domains separately; different fields in Pushshift API
				if "/" in url_clean:
					urls.append(url)
				else:
					domains.append(url_clean)
			if urls:
				# Multiple full URLs is supposedly not supported by Pushshift
				submission_parameters["url"] = "\'" + (",".join(urls)) + "\'"
			if domains:
				submission_parameters["domain"] = ",".join(domains)

		# this is where we store our progress
		thread_ids = []
		total_threads = 0
		seen_threads = set()

		# loop through results bit by bit
		while True:
			retries = 0

			response = self.call_pushshift_api("https://api.pushshift.io/reddit/submission/search", params=submission_parameters)
			if response is None:
				return response

			# if this fails, too much is wrong to continue
			if response.status_code != 200:
				self.query.update_status(
					"HTTP Status code %i while receiving thread data from Pushshift API. Not all posts are saved." % (
						response.status_code))
				return None

			threads = response.json()["data"]

			if len(threads) == 0:
				# we're done here, no more results will be coming
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
						"subreddit": thread["subreddit"],
						"body": thread.get("selftext", "").strip().replace("\r", ""),
						"subject": thread["title"],
						"author": thread["author"],
						"image_file": thread["url"] if image_match.search(thread["url"]) else "",
						"domain": thread["domain"],
						"url": thread["url"],
						"image_md5": "",
						"country_code": "",
						"country_name": "",
						"parent": "",
						"score": thread.get("score", 0)
					})

					# this is the only way to go to the next page right now...
					submission_parameters["after"] = thread["created_utc"]
					total_threads += 1

			# update status
			self.query.update_status("Retrieved %i threads via Pushshift API." % total_threads)

		# if we want full thread data, we need the comment IDs for all threads
		chunked_index = 0
		if query["full_thread"]:
			chunked_search = True
			chunks = []
			chunk = []

			threads_checked = 0
			for thread_id in seen_threads:
				response = self.call_pushshift_api("https://api.pushshift.io/reddit/submission/comment_ids/%s" % thread_id)
				if response is None:
					return response

				# we can continue if this is the case but some posts will be missing
				if response.status_code != 200:
					self.query.update_status(
						"HTTP Status code %i while receiving thread comment IDs from Pushshift API. Not all posts are saved." % (
							response.status_code))
					continue

				# divide the results in 500-ID chunks
				comment_ids = response.json()["data"]
				for comment_id in comment_ids:
					if len(chunk) == 500:
						chunks.append(chunk)
						chunk = []

					chunk.append(comment_id)

				threads_checked += 1
				self.query.update_status("Fetched post IDs for %i of %i threads via Pushshift API..." % (threads_checked, len(seen_threads)))

			# full thread search overrides other search params
			chunks.append(chunk)
			post_parameters["q"] = ""
			post_parameters["after"] = ""
			post_parameters["before"] = ""

		else:
			# non-chunked search, if we're not searching by thread
			chunked_search = False
			chunks = []

		# okay, search the pushshift API for posts
		# we have two modes here: by keyword, or by ID. ID is set above where
		# ID chunks are defined: these chunks are used here if available
		seen_posts = set()

		# do we need to query posts at all?
		# Yes if explicitly stated with the 'full thread' checkmark
		# or if post bodies need to be searched.
		do_posts_search = chunked_search or query["body_query"]

		while do_posts_search:
			# chunked search: search within the given IDs only
			if chunked_search:
				if len(chunks) <= chunked_index:
					# we're out of chunks - done fetching data
					break

				post_parameters["ids"] = ",".join(chunks[chunked_index])
				chunked_index += 1

			response = self.call_pushshift_api("https://api.pushshift.io/reddit/comment/search", params=post_parameters)
			if response is None:
				return response

			if retries >= max_retries:
				self.log.error("Error during pushshift fetch of query %s" % self.query.key)
				self.query.update_status("Error while searching for posts on Pushshift")
				return None

			# this is bad - return what we have so far, but also warn
			if response.status_code != 200:
				self.query.update_status(
					"HTTP Status code %i while receiving post data from Pushshift API. Not all posts are saved." % (
						response.status_code))
				break

			# no more posts
			posts = response.json()["data"]
			if len(posts) == 0 and not chunked_search:
				# this could happen in some edge cases if we're searching by
				# chunk (if no IDs in the chunk match the other parameters)
				# so only break if that's not the case
				break

			# store post data
			for post in posts:
				if post["id"] not in seen_posts:
					seen_posts.add(post["id"])
					return_posts.append({
						"thread_id": post["link_id"].split("_")[1],
						"id": post["id"],
						"timestamp": post["created_utc"],
						"body": post["body"].strip().replace("\r", ""),
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
						# this is the only way to go to the next page right now...
						post_parameters["after"] = post["created_utc"]

					total_posts += 1

			# update our progress
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
		"""
		Unused but mandated by abstract class.

		:param post_ids:
		:return:
		"""
		pass

	def fetch_threads(self, thread_ids):
		"""
		Unused but mandated by abstract class.

		:param thread_ids:
		:return:
		"""
		pass

	def fetch_sphinx(self, where, replacements):
		"""
		Unused but mandated by abstract class.

		:param where:
		:param replacements:
		:return:
		"""
		pass

	def call_pushshift_api(self, *args, **kwargs):
		"""
		Call pushshift API and don't crash (immediately) if it fails

		:param args:
		:param kwargs:
		:return: Response, or `None`
		"""
		retries = 0
		while retries < self.max_retries:
			try:
				response = requests.get(*args, **kwargs)
				#print(response.get_url())
				break
			except requests.RequestException:
				retries += 1

		if retries >= self.max_retries:
			self.log.error("Error during pushshift fetch of query %s" % self.query.key)
			self.query.update_status("Error while searching for posts on Pushshift")
			return None

		return response