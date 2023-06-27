import requests
import json
import time
import re

from backend.lib.search import Search
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException, QueryNeedsExplicitConfirmationException
from common.lib.helpers import UserInput, timify_long

from common.config_manager import config


class SearchReddit(Search):
	"""
	Search Reddit

	Defines methods to fetch Reddit data on demand
	"""
	type = "reddit-search"  # job ID
	category = "Search"  # category
	title = "Reddit Search"  # title displayed in UI
	description = "Query the Pushshift API to retrieve Reddit posts and threads matching the search parameters"  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI
	is_local = False  # Whether this datasource is locally scraped
	is_static = False  # Whether this datasource is still updated

	references = [
		"[API documentation](https://github.com/pushshift/api)",
		"[r/pushshift](https://www.reddit.com/r/pushshift/)",
		"[Baumgartner, J., Zannettou, S., Keegan, B., Squire, M., & Blackburn, J. (2020). The Pushshift Reddit Dataset. *Proceedings of the International AAAI Conference on Web and Social Media*, 14(1), 830-839.](https://ojs.aaai.org/index.php/ICWSM/article/view/7347)"
	]

	# not available as a processor for existing datasets
	accepts = [None]

	max_workers = 1
	max_retries = 5

	rate_limit = 0
	request_timestamps = []

	options = {
		"wildcard-warning": {
			"type": UserInput.OPTION_INFO,
			"help": "The requirement for searching by keyword has been lifted for your account; you can search by "
					"date range only. This can potentially return hundreds of millions of posts, so **please be "
					"careful** when using this privilege.",
			"requires": "reddit-search.can_query_without_keyword"
		},
		"pushshift_track": {
			"type": UserInput.OPTION_CHOICE,
			"help": "API version",
			"options": {
				"beta": "Beta (new version)",
				"regular": "Regular"
			},
			"default": "beta",
			"tooltip": "The beta version retrieves more comments per request but may be incomplete."
		},
		"board": {
			"type": UserInput.OPTION_TEXT,
			"help": "Subreddit(s)",
			"tooltip": "Comma-separated"
		},
		"divider": {
			"type": UserInput.OPTION_DIVIDER
		},
		"intro": {
			"type": UserInput.OPTION_INFO,
			"help": "Reddit data is retrieved from [Pushshift](https://pushshift.io) (see also [this "
					"paper](https://ojs.aaai.org/index.php/ICWSM/article/view/7347)). Note that Pushshift's dataset "
					"*may not be complete* depending on the parameters used,"
					" data from the last few days might not be there yet,"
					" and post scores can be out of date. "
					"See [this paper](https://arxiv.org/pdf/1803.05046.pdf) for an overview of the gaps in data. "
					"Double-check manually or via the official Reddit API if completeness is a concern. Check the "
					"documentation ([beta](https://beta.pushshift.io/redoc), [regular](https://github.com/pushshift/api)) for "
					"more information (e.g. query syntax)."
		},
		"body_match": {
			"type": UserInput.OPTION_TEXT,
			"help": "Message search",
			"tooltip": "Matches anything in the body of a comment or post."
		},
		"subject_match": {
			"type": UserInput.OPTION_TEXT,
			"help": "Subject search",
			"tooltip": "Matches anything in the title of a post."
		},
		"subject_url": {
			"type": UserInput.OPTION_TEXT,
			"help": "URL/domain in post",
			"tooltip": "Regular API only; Filter for posts that link to certain sites or domains (e.g. only posts linking to reddit.com)",
		},
		"divider-2": {
			"type": UserInput.OPTION_DIVIDER
		},
		"daterange": {
			"type": UserInput.OPTION_DATERANGE,
			"help": "Date range"
		},
		"search_scope": {
			"type": UserInput.OPTION_CHOICE,
			"help": "Search scope",
			"options": {
				"op-only": "Opening posts only (no replies/comments)",
				"posts-only": "All matching posts",
			},
			"default": "posts-only"
		}
	}

	config = {
		"reddit-search.can_query_without_keyword": {
			"type": UserInput.OPTION_TOGGLE,
			"help": "Can query without keyword",
			"default": False,
			"tooltip": "Allows users to query Pushshift without specifying a keyword. This can lead to HUGE datasets!"
		}
	}

	# These change depending on the API type used,
	# but should be globally accessible.
	submission_endpoint = None
	comment_endpoint = None
	api_type = None
	since = "since"
	after = "after"

	@staticmethod
	def build_query(query):
		"""
		Determine API call parameters

		Decides what endpoints to call and with which parameters based on the
		parameters provided by the user. There is some complexity here because
		we support two versions of the API, each with their own protocol.

		:param dict query:  Query parameters, as part of the DataSet object
		:return tuple:  Tuple of tuples. First tuple is (submissions endpoint,
		submission parameters), the second the same but for replies.
		"""
		api_type = query.get("pushshift_track", "beta")

		# first, build the request parameters
		if api_type == "regular":
			submission_endpoint = "https://api.pushshift.io/reddit/submission/search"
			post_endpoint = "https://api.pushshift.io/reddit/comment/search"

			post_parameters = {
				"order": "asc",
				"sort_type": "created_utc",
				"size": 100,  # max value
				"metadata": True
			}
			since = "after"
			until = "before"

		# beta fields are a bit different.
		elif api_type == "beta":
			submission_endpoint = "https://beta.pushshift.io/reddit/search/submissions"
			post_endpoint = "https://beta.pushshift.io/reddit/search/comments"

			# For beta requests, we're sorting by IDs so we're not missing data.
			# This is unavailable for the regular API.
			post_parameters = {
				"sort_type": "created_utc",
				"order": "asc",
				"limit": 1000  # max value
			}
			since = "since"
			until = "until"

		else:
			raise NotImplementedError()

		if query["min_date"]:
			post_parameters[since] = int(query["min_date"])

		if query["max_date"]:
			post_parameters[until] = int(query["max_date"])

		if query["board"] and query["board"] != "*":
			post_parameters["subreddit"] = query["board"]

		if query["body_match"]:
			post_parameters["q"] = query["body_match"]
		else:
			post_parameters["q"] = ""

		# first, search for threads - this is a separate endpoint from comments
		submission_parameters = post_parameters.copy()
		submission_parameters["selftext"] = submission_parameters["q"]

		if query["subject_match"]:
			submission_parameters["title"] = query["subject_match"]

		# Check whether only OPs linking to certain URLs should be retrieved.
		# Only available for the regular API.
		if query.get("subject_url", None):
			urls = []
			domains = []

			if "," in query["subject_url"]:
				urls_input = query["subject_url"].split(",")
			elif "|" in query["subject_url"]:
				urls_input = query["subject_url"].split("|")
			else:
				urls_input = [query["subject_url"]]

			# Input strings
			for url in urls_input:
				# Some cleaning
				url = url.strip()
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

		return (
			(submission_endpoint, submission_parameters),
			(post_endpoint, post_parameters),
		)

	def get_items(self, query):
		"""
		Execute a query; get post data for given parameters

		This queries the Pushshift API to find posts and threads mathcing the
		given parameters.

		:param dict query:  Query parameters, as part of the DataSet object
		:return list:  Posts, sorted by thread and post ID, in ascending order
		"""
		scope = query.get("search_scope")
		submission_call, post_call = self.build_query(query)

		# set up query
		total_posts = 0
		max_retries = 3

		# rate limits are not returned by the API server anymore,
		# so we're manually setting it to 120
		self.rate_limit = 120

		# this is where we store our progress
		total_threads = 0
		seen_threads = set()
		expected_results = query.get("expected-results", 0)

		# loop through results bit by bit
		while True:
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while fetching thread data from the Pushshift API")

			retries = 0
			response = self.call_pushshift_api(*submission_call)

			if response is None:
				return response

			threads = response.json()["data"]

			if len([t for t in threads if t["id"] not in seen_threads]) == 0:
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
					
					# Increase the time.
					# this is the only way to go to the next page right now...
					submission_call[1]["after"] = thread["created_utc"]
					
					total_threads += 1

			# update status
			if expected_results:
				self.dataset.update_progress(total_threads / expected_results)
			self.dataset.update_status("Received %s of ~%s posts and threads from Reddit via Pushshift's API" % ("{:,}".format(total_threads), "{:,}".format(expected_results) if expected_results else "unknown"))

		# okay, search the pushshift API for posts
		# we have two modes here: by keyword, or by ID. ID is set above where
		# ID chunks are defined: these chunks are used here if available
		seen_posts = set()

		# only query for individual posts if no subject keyword is given
		# since individual posts don't have subjects so if there is a subject
		# query no results should be returned
		do_body_query = not bool(query.get("subject_match", "")) and not bool(
			query.get("subject_url", "")) and scope != "op-only"

		while do_body_query:
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while fetching post data from the Pushshift API")

			response = self.call_pushshift_api(*post_call)

			if response is None:
				return response

			if retries >= max_retries:
				self.log.error("Error during pushshift fetch of query %s" % self.dataset.key)
				self.dataset.update_status("Error while searching for posts on Pushshift")
				return None

			# no more posts
			posts = response.json()["data"]

			if len([p for p in posts if p["id"] not in seen_posts]) == 0:
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
					
					# Increase the time.
					# this is the only way to go to the next page right now...
					post_call[1][self.since] = post["created_utc"]

					total_posts += 1

			# update our progress
			# update status
			if expected_results:
				self.dataset.update_progress((total_threads + total_posts) / expected_results)
			self.dataset.update_status("Received %s of ~%s posts and threads from Reddit via Pushshift's API" % ("{:,}".format(total_posts + total_threads), "{:,}".format(expected_results) if expected_results else "unknown"))

		# and done!
		if total_posts == 0 and total_threads == 0:
			self.dataset.update_status("No posts found")

	@staticmethod
	def post_to_4cat(post):
		"""
		Convert a pushshift post object to 4CAT post data

		:param dict post:  Post data, as from the pushshift API
		:return dict:  Re-formatted data
		"""

		return {
			"thread_id": post["link_id"].split("_").pop(),
			"id": post["id"],
			"timestamp": post["created_utc"],
			"body": post["body"].strip().replace("\r", ""),
			"subject": "",
			"author": post["author"],
			"author_flair": post.get("author_flair_text", ""),
			"post_flair": "",
			"domain": "",
			"url": "",
			"image_file": "",
			"image_md5": "",
			"subreddit": post["subreddit"],
			"parent": post["parent_id"],
			# this is missing sometimes, but upon manual inspection
			# the post always has 1 point
			"score": post.get("score", 1)
		}

	@staticmethod
	def thread_to_4cat(thread):
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
			"author_flair": thread.get("author_flair_text", ""),
			"post_flair": thread.get("link_flair_text", ""),
			"image_file": thread.get("url", "") if thread.get("url") and image_match.search(thread.get("url", "")) else "",
			"domain": thread.get("domain", ""),
			"url": thread.get("url", ""),
			"image_md5": "",
			"subreddit": thread["subreddit"],
			"parent": "",
			"score": thread.get("score", 0)
		}

	def call_pushshift_api(self, *args, **kwargs):
		"""
		Call pushshift API and don't crash (immediately) if it fails

		Will also try to respect the rate limit, waiting before making a
		request until it will not violate the rate limit.

		:param args:
		:param kwargs:
		:return: Response, or `None`
		"""

		retries = 0
		while retries < self.max_retries:
			try:
				self.wait_until_window()
				response = requests.get(*args, **kwargs)
				self.request_timestamps.append(time.time())
				if response.status_code == 200:
					break
				else:
					raise RuntimeError("HTTP %s" % response.status_code)
			except (RuntimeError, requests.RequestException) as e:
				self.log.info("Error %s while querying Pushshift API - waiting 15 seconds and retrying..." % e)
				time.sleep(15)
				retries += 1

		if retries >= self.max_retries:
			self.log.error("Error during Pushshift fetch of query %s" % self.dataset.key)
			self.dataset.update_status("Error while searching for posts on Pushshift - API did not respond as expected")
			return None

		return response

	@staticmethod
	def get_expected_results(endpoint, parameters, api_type):
		"""
		Get expected result size for a query

		We're not using call_pushshift_api here because that cannot be called
		statically, which is necessary because this is called from within
		validate_query.

		:param str endpoint:  URL of the API endpoint
		:param dict parameters:  Call parameters
		:param api_type: Type of API (regular or beta)

		:return:  Number of expected results, or `None`
		"""
		parameters.update({"metadata": "true", "size": 0,"track_total_hits": True})

		retries = 0
		response = None

		while retries < 3:
			try:
				response = requests.get(endpoint, parameters, timeout=10)
				break
			except requests.RequestException:
				retries += 1
				time.sleep(retries * 5)
				continue

		if not response or response.status_code != 200:
			return None
		else:
			try:
				return response.json()["metadata"]["es"]["hits"]["total"]["value"]
			except (json.JSONDecodeError, KeyError):
				return None

	def wait_until_window(self):
		"""
		Wait until a request can be made outside of the rate limit

		If we have made more requests in the window (one minute) than allowed
		by the rate limit, wait until that is no longer the case.
		"""
		window_start = time.time() - 60
		has_warned = False

		while len([timestamp for timestamp in self.request_timestamps if timestamp >= window_start]) >= self.rate_limit:
			if not has_warned:
				self.log.info("Hit Pushshift rate limit - throttling...")
				has_warned = True

			time.sleep(0.25)  # should be enough

		# clean up timestamps outside of window
		self.request_timestamps = [timestamp for timestamp in self.request_timestamps if timestamp >= window_start]

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
		boards = [r_prefix.sub("", board).strip() for board in query.get("board", "").split(",") if board.strip()]

		if not boards:
			raise QueryParametersException("Please provide a board or a comma-separated list of boards to query.")

		# ignore leading r/ for boards
		query["board"] = ",".join(boards)

		keywordless_query = config.get("reddit-search.can_query_without_keyword", False, user=user)

		# this is the bare minimum, else we can't narrow down the full data set
		if not user.is_admin and not keywordless_query and not query.get(
				"body_match", "").strip() and not query.get("subject_match", "").strip() and not query.get(
			"subject_url", ""):
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

		# URL queries are not possible (yet) for the beta API
		if query.get("pushshift_track") == "beta" and query.get("subject_url", None):
			raise QueryParametersException("URL querying is not possible (yet) for the beta endpoint.")

		# both dates need to be set, or none
		if query.get("min_date", None) and not query.get("max_date", None):
			raise QueryParametersException("When setting a date range, please provide both an upper and lower limit.")

		# the dates need to make sense as a range to search within
		query["min_date"], query["max_date"] = query.get("daterange")

		if "*" in query.get("body_match", "") and not keywordless_query:
			raise QueryParametersException(
				"Wildcard queries are not allowed as they typically return too many results to properly process.")

		if "*" in query.get("board", "") and not keywordless_query:
			raise QueryParametersException(
				"Wildcards are not allowed for boards as this typically returns too many results to properly process.")

		del query["daterange"]

		params = SearchReddit.build_query(query)
		expected_posts = SearchReddit.get_expected_results(*params[0], query.get("pushshift_track", "regular"))
		if not expected_posts:
			expected_posts = 0

		# determine how many results to expect
		# this adds a small delay since we need to talk to the API before
		# returning to the user, but the benefit is that we reduce the amount
		# of too-large queries (because users are warned beforehand) and can
		# give a progress indication for queries that do go through
		if query.get("search_scope") != "op-only":
			expected_replies = SearchReddit.get_expected_results(*params[1], query.get("pushshift_track", "regular"))
			expected_posts += expected_replies if expected_replies else 0

		if expected_posts:
			pps = 672 if query.get("pushshift_track") == "beta" else 44
			expected_seconds = int(expected_posts / pps)  # seems to be about this
			expected_time = timify_long(expected_seconds)
			query["expected-results"] = expected_posts

			if expected_seconds > 1800 and not query.get("frontend-confirm"):
				raise QueryNeedsExplicitConfirmationException(
					"This query will return approximately %s items. This will take a long time (approximately %s)."
					" Are you sure you want to run this query?" % ("{:,}".format(expected_posts), expected_time))

		# if we made it this far, the query can be executed
		return query
