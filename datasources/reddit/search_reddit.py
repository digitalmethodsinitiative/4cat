"""
Search reddit
"""
import requests
import shutil
import re

from backend.abstract.processor import BasicProcessor
from backend.lib.dataset import DataSet
from backend.lib.helpers import posts_to_csv


class SearchReddit(BasicProcessor):
	"""
	Convert a CSV file to JSON
	"""
	type = "reddit-search"  # job type ID
	category = "Search"  # category
	title = "Reddit Search"  # title displayed in UI
	description = "Query the Pushshift API to retrieve Reddit posts and threads matching the search parameters"  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	# not available as a processor for existing datasets
	accepts = [None]

	max_workers = 1
	max_retries = 3

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
		posts = self.execute_string_query(query_parameters)

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
											parent=self.dataset.key, extension=available_processors[next_type]["extension"])
					self.queue.add_job(next_type, remote_id=next_analysis.key)

		# see if we need to register the result somewhere
		if query_parameters.get("copy_to", None):
			# copy the results to an arbitrary place that was passed
			if self.dataset.get_results_path().exists():
				# but only if we actually have something to copy
				shutil.copyfile(self.dataset.get_results_path(), query_parameters.get("copy_to"))
			else:
				# if copy_to was passed, that means it's important that this
				# file exists somewhere, so we create it as an empty file
				with open(query_parameters.get("copy_to"), "w") as empty_file:
					empty_file.write("")

		self.dataset.finish(num_rows=num_posts)

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

				url_clean = url.replace("http://", "")
				url_clean = url.replace("https://", "")
				url_clean = url.replace("www.", "")

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

			response = self.call_pushshift_api("https://api.pushshift.io/reddit/submission/search",
											   params=submission_parameters)
			if response is None:
				return response

			# if this fails, too much is wrong to continue
			if response.status_code != 200:
				self.dataset.update_status(
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
				if thread.get("promoted", False):
					continue

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
			self.dataset.update_status("Retrieved %i threads via Pushshift API." % total_threads)

		# if we want full thread data, we need the comment IDs for all threads
		chunked_index = 0
		if query["full_thread"]:
			chunked_search = True
			chunks = []
			chunk = []

			threads_checked = 0
			for thread_id in seen_threads:
				response = self.call_pushshift_api(
					"https://api.pushshift.io/reddit/submission/comment_ids/%s" % thread_id)
				if response is None:
					return response

				# we can continue if this is the case but some posts will be missing
				if response.status_code != 200:
					self.dataset.update_status(
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
				self.dataset.update_status(
					"Fetched post IDs for %i of %i threads via Pushshift API..." % (threads_checked, len(seen_threads)))

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
				self.log.error("Error during pushshift fetch of query %s" % self.dataset.key)
				self.dataset.update_status("Error while searching for posts on Pushshift")
				return None

			# this is bad - return what we have so far, but also warn
			if response.status_code != 200:
				self.dataset.update_status(
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
				if post.get("promoted", False):
					continue
					
				if post["id"] not in seen_posts:
					seen_posts.add(post["id"])
					return_posts.append({
						"thread_id": post["link_id"].split("_")[1],
						"id": post["id"],
						"timestamp": post["created_utc"],
						"body": post["body"].strip().replace("\r", ""),
						"subject": "",
						"author": post["author"],
						"domain": "",
						"url": "",
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
			self.dataset.update_status("Found %i posts via Pushshift API..." % total_posts)

		# and done!
		return return_posts

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
				# print(response.get_url())
				break
			except requests.RequestException:
				retries += 1

		if retries >= self.max_retries:
			self.log.error("Error during pushshift fetch of query %s" % self.dataset.key)
			self.dataset.update_status("Error while searching for posts on Pushshift")
			return None

		return response
