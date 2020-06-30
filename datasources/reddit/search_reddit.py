import requests
import re

from backend.abstract.search import Search
from backend.lib.exceptions import QueryParametersException, ProcessorInterruptedException


class SearchReddit(Search):
	"""
	Search 4chan corpus

	Defines methods that are used to query the 4chan data indexed and saved.
	"""
	type = "reddit-search"  # job ID
	category = "Search"  # category
	title = "Reddit Search"  # title displayed in UI
	description = "Query the Pushshift API to retrieve Reddit posts and threads matching the search parameters"  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	# not available as a processor for existing datasets
	accepts = [None]

	max_workers = 1
	max_retries = 3

	def get_posts_simple(self, query):
		"""
		In the case of Reddit, there is no need for multiple pathways, so we
		can route it all to the one post query method.
		:param query:
		:return:
		"""
		return self.get_posts_complex(query)

	def get_posts_complex(self, query):
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
		if query["body_match"]:
			post_parameters["q"] = query["body_match"]
		else:
			post_parameters["q"] = ""

		# set up query
		total_posts = 0
		return_posts = []
		max_retries = 3

		# first, search for threads - this is a separate endpoint from comments
		submission_parameters = post_parameters.copy()
		submission_parameters["selftext"] = submission_parameters["q"]

		if query["subject_match"]:
			submission_parameters["title"] = query["subject_match"]

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
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while fetching thread data from the Pushshift API")

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
				self.log.warning("HTTP Status code %i while receiving thread data from Pushshift API. Not all posts are saved." % response.status_code)
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
					yield self.thread_to_4cat(thread)

					# this is the only way to go to the next page right now...
					submission_parameters["after"] = thread["created_utc"]
					total_threads += 1

			# update status
			self.dataset.update_status("Retrieved %i threads via Pushshift API." % total_threads)

		# okay, search the pushshift API for posts
		# we have two modes here: by keyword, or by ID. ID is set above where
		# ID chunks are defined: these chunks are used here if available
		seen_posts = set()

		# only query for individual posts if there is a body keyword
		# since individual posts don't have subjects
		do_body_query = bool(query["body_match"].strip()) or not bool(query["subject_match"].strip())

		while do_body_query:
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while fetching post data from the Pushshift API")

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
				self.log.warning("HTTP Status code %i while receiving thread data from Pushshift API. Not all posts are saved." % response.status_code)
				break

			# no more posts
			posts = response.json()["data"]
			if len(posts) == 0:
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
					yield self.post_to_4cat(post)
					post_parameters["after"] = post["created_utc"]

					total_posts += 1

			# update our progress
			self.dataset.update_status("Found %i posts via Pushshift API..." % total_posts)

		# and done!
		if total_posts == 0 and total_threads == 0:
			self.dataset.update_status("No posts found")

	def fetch_posts(self, post_ids, where=None, replacements=None):
		"""
		Fetch post data from Pushshift API by post ID

		:param list post_ids:  List of post IDs to return data for
		:return list: List of posts, with a dictionary representing the record for each post
		"""
		chunk_size = 500
		posts = []

		# search threads in chunks
		offset = 0
		while True:
			chunk = post_ids[offset:offset + chunk_size]
			if not chunk:
				break

			response = self.call_pushshift_api("https://api.pushshift.io/reddit/comment/search?ids=" + ",".join(chunk))
			if not response:
				break

			if response.status_code != 200:
				break

			for post in response.json()["data"]:
				posts.append(self.post_to_4cat(post))

			offset += chunk_size

		return posts

	def fetch_threads(self, thread_ids):
		"""
		Get all posts for given thread IDs

		The pushshift API at this time has no endpoint that retrieves comments
		for multiple threads at the same time, so unfortunately we have to go
		through the threads one by one.

		:param tuple thread_ids:  Thread IDs to fetch posts for.
		:return list:  A list of posts, as dictionaries.
		"""
		posts = []

		# search threads in chunks
		offset = 0
		for thread_id in thread_ids:
			offset += 1
			self.dataset.update_status("Retrieving posts for thread %i of %i" % (offset, len(thread_ids)))
			response = self.call_pushshift_api("https://api.pushshift.io/reddit/comment/search",
											   params={"link_id": thread_id})
			if response is None:
				break

			if response.status_code != 200:
				break

			posts_raw = response.json()["data"]
			for post in posts_raw:
				posts.append(self.post_to_4cat(post))

		return posts

	def get_thread_sizes(self, thread_ids, min_length):
		"""
		Get thread lengths for all threads

		:param tuple thread_ids:  List of thread IDs to fetch lengths for
		:param int min_length:  Min length for a thread to be included in the
		results
		:return dict:  Threads sizes, with thread IDs as keys
		"""
		chunk_size = 500
		chunks = []
		lengths = {}
		thread_ids = list(set(thread_ids))  # deduplicate

		# search threads in chunks
		offset = 0
		while True:
			chunk = thread_ids[offset:offset + chunk_size]
			if not chunk:
				break

			response = self.call_pushshift_api("https://api.pushshift.io/reddit/submission/search?ids=" + ",".join(chunk))
			if response is None:
				break

			if response.status_code != 200:
				break

			for thread in response.json()["data"]:
				length = thread["num_comments"]
				if length >= min_length:
					lengths[thread["id"]] = length

			offset += chunk_size

		return lengths

	def post_to_4cat(self, post):
		"""
		Convert a pushshift post object to 4CAT post data

		:param dict post:  Post data, as from the pushshift API
		:return dict:  Re-formatted data
		"""
		return {
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
			"subreddit": post["subreddit"],
			"parent": post["parent_id"],
			# this is missing sometimes, but upon manual inspection
			# the post always has 1 point
			"score": post.get("score", 1)
		}

	def thread_to_4cat(self, thread):
		"""
		Convert a pushshift thread object to 4CAT post data

		:param dict post:  Post data, as from the pushshift API
		:return dict:  Re-formatted data
		"""
		image_match = re.compile(r"\.(jpg|jpeg|png|gif|webm|mp4)$", flags=re.IGNORECASE)

		return {
			"thread_id": thread["id"],
			"id": thread["id"],
			"timestamp": thread["created_utc"],
			"body": thread.get("selftext", "").strip().replace("\r", ""),
			"subject": thread["title"],
			"author": thread["author"],
			"image_file": thread["url"] if image_match.search(thread["url"]) else "",
			"domain": thread["domain"],
			"url": thread["url"],
			"image_md5": "",
			"country_code": "",
			"country_name": "",
			"subreddit": thread["subreddit"],
			"parent": "",
			"score": thread.get("score", 0)
		}

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
				break
			except requests.RequestException as e:
				self.log.info("Error %s while querying Pushshift API - retrying..." % e)
				retries += 1

		if retries >= self.max_retries:
			self.log.error("Error during pushshift fetch of query %s" % self.dataset.key)
			self.dataset.update_status("Error while searching for posts on Pushshift")
			return None

		return response

	def validate_query(query, request, user):
		"""
		Validate input for a dataset query on the 4chan data source.

		Will raise a QueryParametersException if invalid parameters are
		encountered. Mutually exclusive parameters may also be sanitised by
		ignoring either of the mutually exclusive options.

		:param dict query:  Query parameters, from client-side.
		:param request:  Flask request
		:param User user:  User object of user who has submitted the query
		:return dict:  Safe query parameters
		"""
		# we need a board!
		r_prefix = re.compile(r"^/?r/")
		boards = [r_prefix.sub("", board) for board in query.get("board", "").split(",") if board.strip()]

		if not boards:
			raise QueryParametersException("Please provide a board or a comma-separated list of boards to query.")

		# ignore leading r/ for boards
		query["board"] = ",".join(boards)
		
		# this is the bare minimum, else we can't narrow down the full data set
		if not user.is_admin() and not user.get_value("reddit.can_query_without_keyword", False) and not query.get("body_match", "").strip() and not query.get("subject_match", "").strip():
			raise QueryParametersException("Please provide a body query or subject query.")

		# body query and full threads are incompatible, returning too many posts
		# in most cases
		if query.get("body_match", None):
			if "full_threads" in query:
				del query["full_threads"]

		# Make sure no body or subject searches starting with just a minus sign are possible, e.g. "-Trump"
		if query.get("body_match", None) or query.get("subject_match", None):

			queries_to_check = []
			if query.get("body_match", None):
				queries_to_check += [body_query.strip() for body_query in query["body_match"].split(" ")]
			if query.get("subject_match", None):
				queries_to_check += [subject_query.strip() for subject_query in query["subject_match"].split(" ")]
			startswith_minus = [query_check.startswith("-") for query_check in queries_to_check]
			if all(startswith_minus):
				raise QueryParametersException("Please provide body queries that do not start with a minus sign.")

		# only one of two dense threads options may be chosen at the same time, and
		# it requires valid density and length parameters. full threads is implied,
		# so it is otherwise left alone here
		if query.get("search_scope", "") == "dense-threads":
			try:
				dense_density = int(query.get("scope_density", ""))
			except ValueError:
				raise QueryParametersException("Please provide a valid numerical density percentage.")

			if dense_density < 15 or dense_density > 100:
				raise QueryParametersException("Please provide a density percentage between 15 and 100.")

			try:
				dense_length = int(query.get("scope_length", ""))
			except ValueError:
				raise QueryParametersException("Please provide a valid numerical dense thread length.")

			if dense_length < 30:
				raise QueryParametersException("Please provide a dense thread length of at least 30.")

		# both dates need to be set, or none
		if query.get("min_date", None) and not query.get("max_date", None):
			raise QueryParametersException("When setting a date range, please provide both an upper and lower limit.")

		# the dates need to make sense as a range to search within
		if query.get("min_date", None) and query.get("max_date", None):
			try:
				before = int(query.get("max_date", ""))
				after = int(query.get("min_date", ""))
			except ValueError:
				raise QueryParametersException("Please provide valid dates for the date range.")

			if before < after:
				raise QueryParametersException(
					"Please provide a valid date range where the start is before the end of the range.")

			query["min_date"] = after
			query["max_date"] = before

		is_placeholder = re.compile("_proxy$")
		filtered_query = {}
		for field in query:
			if not is_placeholder.search(field):
				filtered_query[field] = query[field]

		# if we made it this far, the query can be executed
		return filtered_query
