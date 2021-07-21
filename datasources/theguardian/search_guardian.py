"""
Search The Guardian climate change corpus
"""
import datedelta
import requests
import datetime
import re

from backend.abstract.search import SearchWithScope
from common.lib.helpers import UserInput
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException


class SearchGuardian(SearchWithScope):
	"""
	Search The Guardian climate change corpus

	Defines methods that are used to query the Guardian data via PENELOPE.
	"""
	type = "theguardian-search"  # job ID
	category = "Search"  # category
	title = "The Guardian Climate Change Search"  # title displayed in UI
	description = "Queries the VUB's The Guardian Climate Change dataset via PENELOPE for articles and comments on those articles."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	# not available as a processor for existing datasets
	accepts = [None]

	max_workers = 1
	max_retries = 3

	options = {
		"intro": {
			"type": UserInput.OPTION_INFO,
			"help": "The Guardian data is retrieved via [PENELOPE](https://penelope.vub.be). It covers *The Guardian* "
					"articles related to climate change and also the comments on those articles."
					"Data was collected by PENELOPE until April 24th, 2019."
		},
		"body_match": {
			"type": UserInput.OPTION_TEXT,
			"help": "Content contains"
		},
		"daterange": {
			"type": UserInput.OPTION_DATERANGE,
			"help": "Publication date"
		},
		"search_scope": {
			"type": UserInput.OPTION_CHOICE,
			"help": "Search scope",
			"options": {
				"posts-only": "All matching posts",
				"full-threads": "All posts in threads with matching posts (full threads)",
				"dense-threads": "All posts in threads in which at least x% of posts match (dense threads)"
			},
			"default": "posts-only"
		},
		"scope_density": {
			"type": UserInput.OPTION_TEXT,
			"help": "Min. density %",
			"min": 0,
			"max": 100,
			"default": 15,
			"tooltip": "At least this many % of posts in the thread must match the query"
		},
		"scope_length": {
			"type": UserInput.OPTION_TEXT,
			"help": "Min. dense thread length",
			"min": 30,
			"default": 30,
			"tooltip": "A thread must at least be this many posts long to qualify as a 'dense thread'"
		}
	}

	def get_items_simple(self, query):
		"""
		In the case of The Guardian, there is no need for multiple pathways, so we
		can route it all to the one post query method.
		:param query:
		:return:
		"""
		return self.get_items_complex(query)

	def get_items_complex(self, query):
		"""
		Execute a query; get post data for given parameters

		:param dict query:  Query parameters, as part of the DataSet object
		:return list:  Posts, sorted by thread and post ID, in ascending order
		"""
		start = datetime.datetime.utcfromtimestamp(query["min_date"]).strftime("%Y-%m-%d")
		end = datetime.datetime.utcfromtimestamp(query["max_date"]).strftime("%Y-%m-%d")

		# the first endpoint fetches all articles that match, the second all
		# articles for which at least one comment matches. All comments on
		# matching articles are also queried.
		regex = query["body_match"].replace("*", ".+")
		all_articles = self.call_penelope_api("articles/%s/%s/%s/1000" % (start, end, regex))
		all_comments = self.call_penelope_api("comments/%s/%s/%s/1000" % (start, end, regex))

		# convert API output to 4CAT-compatible data
		articles = [self.thread_to_4cat(article) for article in all_articles]
		comments = []
		for article in all_comments:
			comments += [self.post_to_4cat(comment, self.obj_to_id(article)) for comment in article.get("comments", [])]

		# there is a risk of duplicates if an article matches both for its own
		# content and for a comment, so this next step eliminates any dupes
		heap = list(articles + comments)
		everything = {}
		for item in heap:
			if item["id"] not in everything:
				everything[item["id"]] = item

		# the API's filtering is somewhat rudimentary, so at this point we
		# have *all* comments on matching articles - the next step is to
		# filter these so only matching comments and articles are left
		filtered = []
		for item in [everything[id] for id in everything]:
			if item["timestamp"] >= query["min_date"] and item["timestamp"] < query["max_date"] and re.search(regex,
																											  item[
																												  "body"]):
				filtered.append(item)

		return sorted(filtered, key=lambda item: item["timestamp"])

	def fetch_posts(self, post_ids, where=None, replacements=None, keep_comments=False):
		"""
		Fetch post data from PENELOPE API by post ID

		:param tuple|list post_ids:  List of post IDs to return data for
		:param list where:  Unused
		:param list replacements:  Unused
		:param bool keep_comments:  Include all comments on matching posts in
		the results
		:return list: List of posts, with a dictionary representing the record for each post
		"""
		if not post_ids:
			return []
		# the ids provided to this function are compounds of the item's date
		# and the actual ID - we need the date because that is the only
		# available filter option the API has
		post_dates = [int(id.split("-")[0] + id.split("-")[1] + id.split("-")[2]) for id in post_ids]
		post_dates = [datetime.datetime(int(id.split("-")[0]), int(id.split("-")[1]), int(id.split("-")[2])) for id in post_ids]
		post_ids = [id.split("-")[3] for id in post_ids]

		# run this in 1-month chunks because the API crashes at higher article
		# counts
		start = min(post_dates)
		end = max(post_dates)
		posts = []

		chunk_start = start
		while True:
			chunk_end = chunk_start + datedelta.MONTH
			if chunk_end > end:
				chunk_end = end

			# call API, and pray there are fewer than a 1000 articles in the
			# response
			search_endpoint = "comments/" + chunk_start.strftime("%Y-%m-%d") + "/" + chunk_end.strftime("%Y-%m-%d") + "/.*/" + "1000"
			all_posts = self.call_penelope_api(search_endpoint)

			# the API data is *more* than what we're interested in, so this step
			# narrows it down to what we actually need
			for post in all_posts:
				if post["_id"]["$oid"] not in post_ids:
					continue

				thread = self.thread_to_4cat(post)
				posts.append(thread)
				for comment in post.get("comments", []):
					if keep_comments or post["id"] in post_ids:
						posts.append(self.post_to_4cat(comment, thread_id=self.obj_to_id(post)))

			chunk_start += datedelta.MONTH
			if chunk_start > end:
				break

		return posts

	def fetch_threads(self, thread_ids):
		"""
		Get all posts for given thread IDs

		The penelope API at this time has no endpoint that retrieves comments
		for multiple threads at the same time, so unfortunately we have to go
		through the threads one by one.

		:param tuple thread_ids:  Thread IDs to fetch posts for.
		:return list:  A list of posts, as dictionaries.
		"""
		return self.fetch_posts(post_ids=thread_ids, keep_comments=True)

	def get_thread_sizes(self, thread_ids, min_length):
		"""
		Get thread lengths for all threads

		:param tuple thread_ids:  List of thread IDs to fetch lengths for
		:param int min_length:  Min length for a thread to be included in the
		results
		:return dict:  Threads sizes, with thread IDs as keys
		"""
		posts = self.fetch_threads(thread_ids)
		lengths = {}

		for post in posts:
			if post["thread_id"] not in lengths:
				lengths[post["thread_id"]] = 0

			lengths[post["thread_id"]] += 1

		return {thread_id: lengths[thread_id] for thread_id in lengths if lengths[thread_id] >= min_length}

	def post_to_4cat(self, post, thread_id):
		"""
		Convert a PENELOPE API post object to 4CAT post data

		:param dict post:  Post data, as from the penelope API
		:param thread_id:  ID of thread the post belongs to, as this is not
		part of the post data
		:return dict:  Re-formatted data
		"""
		return {
			"thread_id": thread_id,
			"id": self.obj_to_id(post),
			"timestamp": int(int(post["time_stamp"]["$date"]) / 1000),
			"url": "",
			"subject": "",
			"summary": "",
			"body": post["text"],
			"author": post["author"],
			"score": post.get("recommendation_count", 0),
			"parent": post.get("in_reply_to", thread_id)
		}

	def thread_to_4cat(self, thread):
		"""
		Convert a PENELOPE API thread object to 4CAT post data

		:param dict thread:  Thread data, as from the penelope API
		:return dict:  Re-formatted data
		"""
		return {
			"thread_id": self.obj_to_id(thread),
			"id": self.obj_to_id(thread),
			"timestamp": int(int(thread["date_published"]["$date"]) / 1000),
			"subject": thread["og_fields"]["og:title"],
			"url": thread["url"],
			"summary": thread["description"],
			"body": thread.get("text", ""),
			"author": ", ".join(thread.get("authors", [])),
			"score": 0,
			"parent": ""
		}

	def call_penelope_api(self, endpoint, *args, **kwargs):
		"""
		Call PENELOPE API and don't crash (immediately) if it fails

		:param endpoint: Endpoint to call relative to HTTP root
		:param args:
		:param kwargs:
		:return: Response, or `None`
		"""
		retries = 0
		while retries < self.max_retries:
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while fetching data from the Penelope API")

			try:
				url = "http://penelope.vub.be/guardian-climate-change-data/" + endpoint
				response = requests.get(url, *args, **kwargs)
				break
			except requests.RequestException as e:
				self.log.info("Error %s while querying PENELOPE Guardian API - retrying..." % e)
				retries += 1

		if retries >= self.max_retries:
			self.log.error("Error during PENELOPE fetch of query %s" % self.dataset.key)
			self.dataset.update_status("Error while searching for posts on PENELOPE Guardian API")
			return None
		else:
			return response.json()

	def obj_to_id(self, obj):
		"""
		Get a unique ID for a given object, which can be either an article or
		a comment

		The ID includes the creation date of the object, which is relevant because it is
		the only way to filter via the PENELOPE API.

		:param obj:  Object, a dictionary that is either an article or a comment
		:return:  An ID, in the format YYYY-DD-MM-[ID]
		"""
		if "schema_org_type" in obj and obj.get("schema_org_type") == "http://schema.org/Comment":
			timestamp = datetime.datetime.utcfromtimestamp(int(obj["time_stamp"]["$date"]) / 1000).strftime("%Y-%m-%d")
			return str(timestamp) + "-" + obj["id"]
		else:
			timestamp = datetime.datetime.utcfromtimestamp(int(obj["date_published"]["$date"]) / 1000).strftime("%Y-%m-%d")
			return str(timestamp) + "-" + obj["_id"]["$oid"]

	def validate_query(query, request, user):
		"""
		Validate input for a dataset query on the Guardian data source.

		Will raise a QueryParametersException if invalid parameters are
		encountered. Mutually exclusive parameters may also be sanitised by
		ignoring either of the mutually exclusive options.

		:param dict query:  Query parameters, from client-side.
		:param request:  Flask request
		:param User user:  User object of user who has submitted the query
		:return dict:  Safe query parameters
		"""
		# this is the bare minimum, else we can't narrow down the full data set
		if not query.get("body_match", None) and not query.get("subject_match", None):
			raise QueryParametersException("Please provide a search query")

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

		# the dates need to make sense as a range to search within
		if not all(query.get("daterange")):
			raise QueryParametersException("You must provide a date range")

		query["min_date"], query["max_date"] = query.get("daterange")
		del query["daterange"]

		if query["max_date"] and (query["max_date"] - query["min_date"]) > (86400 * 31 * 6):
			raise QueryParametersException("Date range may span 6 months at most")

		# if we made it this far, the query can be executed
		return query
