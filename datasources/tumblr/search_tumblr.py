"""
Search Tumblr via its API

Can fetch posts from specific blogs or with specific hashtags
"""

import time
import pytumblr
import requests
from requests.exceptions import ConnectionError
from datetime import datetime
from ural import urls_from_text

from common.config_manager import config
from backend.lib.search import Search
from common.lib.helpers import UserInput, strip_tags
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException, ConfigException
from common.lib.item_mapping import MappedItem


__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen", "Tumblr API (api.tumblr.com)"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

class SearchTumblr(Search):
	"""
	Tumblr data filter module.
	"""
	type = "tumblr-search"  # job ID
	category = "Search"  # category
	title = "Search Tumblr"  # title displayed in UI
	description = "Retrieve Tumblr posts by hashtag or blog."  # description displayed in UI
	extension = "ndjson"  # extension of result file, used internally and in UI
	is_local = False	# Whether this datasource is locally scraped
	is_static = False	# Whether this datasource is still updated

	# not available as a processor for existing datasets
	accepts = [None]

	max_workers = 1
	max_retries = 3 # For API and connection retries.
	max_date_retries = 96 + 150 # For checking dates. 96 time retries of -6 hours (24 days), plus 150 extra for 150 weeks (~3 years).
	max_posts = 1000000

	max_posts_reached = False
	api_limit_reached = False

	seen_ids = set()
	client = None
	failed_notes = []
	failed_reblogs = []

	config = {
		# Tumblr API keys to use for data capturing
		'api.tumblr.consumer_key': {
			'type': UserInput.OPTION_TEXT,
			'default': "",
			'help': 'Tumblr Consumer Key',
			'tooltip': "",
		},
		'api.tumblr.consumer_secret': {
			'type': UserInput.OPTION_TEXT,
			'default': "",
			'help': 'Tumblr Consumer Secret Key',
			'tooltip': "",
		},
		'api.tumblr.key': {
			'type': UserInput.OPTION_TEXT,
			'default': "",
			'help': 'Tumblr API Key',
			'tooltip': "",
		},
		'api.tumblr.secret_key': {
			'type': UserInput.OPTION_TEXT,
			'default': "",
			'help': 'Tumblr API Secret Key',
			'tooltip': "",
		}
	}
	references = ["[Tumblr API documentation](https://www.tumblr.com/docs/en/api/v2)"]

	@classmethod
	def get_options(cls, parent_dataset=None, user=None):
		"""
		Check is Tumbler keys configured and if not, requests from User
		"""
		options = {
			"intro": {
				"type": UserInput.OPTION_INFO,
				"help": "Retrieve any kind of Tumblr posts with specific tags or from specific blogs. Gets 100.000 posts "
						"at max. Insert tags or names of blogs, one on each line. You may insert up to ten tags or "
						"blogs.\n\nTumblr tags may include whitespace and commas. A `#` before the tag is optional.\n\n"
						"Tag search only get posts explicitly associated with the exact tag you insert here. Querying "
						"`gogh` will thus not get posts only tagged with `van gogh`. Keyword search is not "
						"allowed by the [Tumblr API](https://api.tumblr.com).\n\nIf this 4CAT reached its Tumblr API rate "
						"limit, try again 24 hours later."
			},
			"search_scope": {
				"type": UserInput.OPTION_CHOICE,
				"help": "Search by",
				"options": {
					"tag": "Tag",
					"blog": "Blog"
				},
				"default": "tag"
			},
			"query": {
				"type": UserInput.OPTION_TEXT_LARGE,
				"help": "Tags/blogs",
				"tooltip": "Separate with commas or new lines."
			},
			"get_notes": {
				"type": UserInput.OPTION_TOGGLE,
				"help": "Get post notes (warning: slow)",
				"tooltip": "Also retrieve post notes. Likes and replies are added to the original post. Text reblogs are added as new posts.",
				"default": False
			}
		}

		try:
			config_keys = SearchTumblr.get_tumblr_keys(user)
		except ConfigException:
			# No 4CAT set keys for user; let user input their own
			options["key-info"] = {
				"type": UserInput.OPTION_INFO,
				"help": "In order to access the Tumblr API, you need to register an application. You can do so "
						"[here](https://www.tumblr.com/oauth/apps) and use the keys below. You will first get the OAuth "
						"Consumer Key and Secret, and then the User Token Key and Secret [after entering them here](ht"
									  "tps://api.tumblr.com/console/calls/user/info) and granting access."
			}
			options["consumer_key"] = {
				"type": UserInput.OPTION_TEXT,
				"sensitive": True,
				"cache": True,
				"help": "OAuth Consumer Key"
			}
			options["consumer_secret"] = {
				"type": UserInput.OPTION_TEXT,
				"sensitive": True,
				"cache": True,
				"help": "OAuth Consumer Secret"
			}
			options["key"] = {
				"type": UserInput.OPTION_TEXT,
				"sensitive": True,
				"cache": True,
				"help": "User Token Key"
			}
			options["secret_key"] = {
				"type": UserInput.OPTION_TEXT,
				"sensitive": True,
				"cache": True,
				"help": "User Token Secret"
			}

		options["divider"] = {
				"type": UserInput.OPTION_DIVIDER
			}
		options["date-intro"] = {
				"type": UserInput.OPTION_INFO,
				"help": "**Note:** The [Tumblr API](https://api.tumblr.com) is volatile: when fetching sporadically used "
						"tags, it may return zero posts, even though older posts exist. To mitigate this, 4CAT decreases "
						"the date parameter (<code>before</code>) with six hours and sends the query again. This often "
						"successfully returns older, un-fetched posts. If it didn't find new data after 96 retries (24 "
						"days), it checks for data up to six years before the last date, decreasing 12 times by 6 months. "
						"If that also results in nothing, it assumes the dataset is complete. Check the oldest post in "
						"your dataset to see if it this is indeed the case and whether any odd time gaps exists."
			}
		options["daterange"] = {
				"type": UserInput.OPTION_DATERANGE,
				"help": "Date range"
			}

		return options

	def get_items(self, query):
		"""
		Fetches data from Tumblr via its API.

		"""

		# ready our parameters
		parameters = self.dataset.get_parameters()
		scope = parameters.get("search_scope", "")
		queries = parameters.get("query").split(", ")
		get_notes = parameters.get("get_notes", False)

		# Store all info here
		results = []

		# Store all notes from posts by blogs here
		all_notes = []

		# Get date parameters
		min_date = parameters.get("min_date", None)
		max_date = parameters.get("max_date", None)

		if min_date:
			min_date = int(min_date)
		if max_date:
			max_date = int(max_date)
		else:
			max_date = int(time.time())

		# Connect to Tumblr API
		try:
			self.client = self.connect_to_tumblr()
		except ConfigException as e:
			self.log.warning(f"Could not connect to Tumblr API: API keys invalid or not set")
			self.dataset.finish_with_error(f"Could not connect to Tumblr API: API keys invalid or not set")
			return
		except ConnectionRefusedError as e:
			client_info = self.client.info()
			self.log.warning(f"Could not connect to Tumblr API: {e}; client_info: {client_info}")
			self.dataset.finish_with_error(f"Could not connect to Tumblr API: {client_info.get('meta', {}).get('status', '')} - {client_info.get('meta', {}).get('msg', '')}")
			return

		# for each tag or blog, get post
		for query in queries:

				# Get posts per tag
				if scope == "tag":
					# Used for getting tagged posts, which uses requests instead.
					api_key = self.parameters.get("consumer_key")
					if not api_key:
						api_key = SearchTumblr.get_tumblr_keys(self.owner)[0]

					new_results = self.get_posts_by_tag(query, max_date=max_date, min_date=min_date, api_key=api_key)

				# Get posts per blog
				elif scope == "blog":
					new_results = self.get_posts_by_blog(query, max_date=max_date, min_date=min_date)

				else:
					self.dataset.update_status("Invalid scope")
					break

				results += new_results

				if self.max_posts_reached:
					self.dataset.update_status("Max posts exceeded")
					break
				if self.api_limit_reached:
					self.dataset.update_status("API limit reached")
					break

		# Loop through the results once to add note data and fetch text reblogs,
		len_results = len(results) # results will change in length when we add reblogs.
		for i in range(len_results):

			post = results[i]

			# Get note information
			if get_notes and not self.max_posts_reached and not self.api_limit_reached:

				# Reblog information is already returned for blog-level searches
				# and is stored as `notes` in the posts themselves.
				# Retrieving notes for tag-based posts must be done one-by-one;
				# fetching them all at once is not supported by the Tumblr API.
				if not "notes" in post:
					self.dataset.update_status("Getting note data for post %i/%i" % (i, len_results))

					# Prepare dicts to pass to `get_post_notes`
					notes = self.get_post_notes(post["blog_name"], post["id"])

					if notes:
						results[i]["notes"] = notes

					# Get the full data for text reblogs and add them as new posts
					for note in notes:
						if note["type"] == "reblog":
							text_reblog = self.get_post_by_id(note["blog_name"], note["post_id"])
							if text_reblog:
								results.append(text_reblog)
		
		self.job.finish()
		return results

	def get_posts_by_tag(self, tag, max_date=None, min_date=None, api_key=None):
		"""
		Get Tumblr posts posts with a certain tag
		:param tag, str: the tag you want to look for
		:param min_date: a unix timestamp, indicates posts should be min_date this date.
		:param max_date: a unix timestamp, indicates posts should be max_date this date.

		:returns: a dict created from the JSON response
		"""
		# Store all posts in here
		all_posts = []

		# Some retries to make sure the Tumblr API actually returns everything.
		retries = 0
		date_retries = 0

		# We're gonna change max_date, so store a copy for reference.
		max_date_original = max_date

		# We use the average time difference between posts to spot possible gaps in the data.
		all_time_difs = []
		avg_time_dif = 0
		time_difs_len = 0

		# Get Tumblr posts until there's no more left.
		while True:
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while fetching tag posts from Tumblr")

			# Stop after max for date reductions
			if date_retries >= self.max_date_retries:
				self.dataset.update_status("No more posts in this date range")
				break

			# Stop after max retries for API/connection stuff
			if retries >= self.max_retries:
				self.dataset.update_status("No more posts")
				break

			try:
				# PyTumblr does not allow to use the `npf` parameter yet 
				# for the `tagged` endpoint (opened a pull request), so
				# we're using requests here.
				params = {
					"tag": tag,
					"api_key": api_key,
					"before": max_date,
					"limit": 20,
					"filter": "raw",
					"npf": True,
					"notes_info": True
				}
				url = "https://api.tumblr.com/v2/tagged"
				response = requests.get(url, params=params)
				posts = response.json()["response"]
				
			except ConnectionError:
				self.update_status("Encountered a connection error, waiting 10 seconds.")
				time.sleep(10)
				retries += 1
				continue

			# Get rid of posts that we already enountered,
			# preventing Tumblr API shenanigans or double posts because of
			# time reductions. Make sure it's no odd error string, though.
			unseen_posts = []
			for check_post in posts:
				# Sometimes the API repsonds just with "meta", "response", or "errors".
				if isinstance(check_post, str):
					self.dataset.update_status("Couldn't add post:", check_post)
					retries += 1
					break
				else:
					retries = 0
					if check_post["id"] not in self.seen_ids:
						unseen_posts.append(check_post)

			posts = unseen_posts

			# For no clear reason, the Tumblr API sometimes provides posts with a higher timestamp than requested.
			# So we have to prevent this manually.
			if max_date_original:
				posts = [post for post in posts if post["timestamp"] <= max_date_original]

			max_date_str = datetime.fromtimestamp(max_date).strftime("%Y-%m-%d %H:%M:%S")

			# except Exception as e:
			# 	print(e)
			# 	self.dataset.update_status("Reached the limit of the Tumblr API. Last timestamp: %s" % str(max_date))
			# 	self.api_limit_reached = True
			# 	break

			# Make sure the Tumblr API doesn't magically stop at an earlier date
			if not posts:

				date_retries += 1

				# We're first gonna check carefully if there's small timegaps by
				# decreasing by six hours.
				# If that didn't result in any new posts, also dedicate 12 date_retries
				# with reductions of six months, just to be sure there's no data from
				# years earlier missing.

				if date_retries < 96:
					max_date -= 21600 # Decrease by six hours
					self.dataset.update_status("Collected %s posts for tag %s, but no new posts returned - decreasing time search with 6 hours to %s to make sure this is really it (retry %s/96)" % (str(len(all_posts)), tag, max_date_str, str(date_retries),))
				elif date_retries <= self.max_date_retries:
					max_date -= 604800 # Decrease by one week
					retry_str = str(date_retries - 96)
					self.dataset.update_status("Collected %s posts for tag %s, but no new posts returned - no new posts found with decreasing by 6 hours, decreasing with a week to %s instead (retry %s/150)" % (str(len(all_posts)), tag, max_date_str, str(retry_str),))

				# We can stop when the max date drops below the min date.
				if min_date:
					if max_date <= min_date:
						break

				continue

			# Append posts to main list
			else:

				# Get all timestamps and sort them.
				post_dates = sorted([post["timestamp"] for post in posts])

				# Get the lowest date and use it as the next "before" parameter.
				max_date = post_dates[0]

				# Tumblr's API is volatile - it doesn't neatly sort posts by date,
				# so it can happen that there's suddenly huge jumps in time.
				# Check if this is happening by extracting the difference between all consecutive dates.
				time_difs = list()
				post_dates.reverse()

				for i, date in enumerate(post_dates):

					if i == (len(post_dates) - 1):
						break

					# Calculate and add time differences
					time_dif = date - post_dates[i + 1]

					# After having collected 250 posts, check whether the time
					# difference between posts far exceeds the average time difference
					# between posts. If it's more than five times this amount,
					# restart the query with the timestamp just before the gap, minus the
					# average time difference up to this point - something might be up with Tumblr's API.
					if len(all_posts) >= 250 and time_dif > (avg_time_dif * 5):

						time_str = datetime.fromtimestamp(date).strftime("%Y-%m-%d %H:%M:%S")
						self.dataset.update_status("Time difference of %s spotted, restarting query at %s" % (str(time_dif), time_str,))

						self.seen_ids.update([post["id"] for post in posts])
						posts = [post for post in posts if post["timestamp"] >= date]
						if posts:
							all_posts += posts

						max_date = date
						break

					time_difs.append(time_dif)

				# To start a new query
				if not posts:
					break

				# Manually check if we have a lower date than the lowest allowed date already (min date).
				# This functonality is not natively supported by Tumblr.
				if min_date:
					if max_date < min_date:

						# Get rid of all the posts that are earlier than the max_date timestamp
						posts = [post for post in posts if post["timestamp"] >= min_date and post["timestamp"] <= max_date_original]

						if posts:
							all_posts += posts
							self.seen_ids.update([post["id"] for post in posts])
						break

				# We got a new post, so we can reset the retry counts.
				date_retries = 0
				retries = 0

				# Add retrieved posts top the main list
				all_posts += posts

				# Add to seen ids
				self.seen_ids.update([post["id"] for post in posts])

				# Add time differences and calculate new average time difference
				all_time_difs += time_difs

				# Make the average time difference a moving average,
				# to be flexible with faster and slower post paces.
				# Delete the first 100 posts every hundred or so items.
				if (len(all_time_difs) - time_difs_len) > 100:
					all_time_difs = all_time_difs[time_difs_len:]
				if all_time_difs:
					time_difs_len = len(all_time_difs)
					avg_time_dif = sum(all_time_difs) / len(all_time_difs)

			if len(all_posts) >= self.max_posts:
				self.max_posts_reached = True
				break

			self.dataset.update_status("Collected %s posts for tag %s, now looking for posts before %s" % (str(len(all_posts)), tag, max_date_str,))

		return all_posts

	def get_posts_by_blog(self, blog, max_date=None, min_date=None):
		"""
		Get Tumblr posts posts with a certain blog
		:param tag, str: the name of the blog you want to look for
		:param min_date: a unix timestamp, indicates posts should be min_date this date.
		:param max_date: a unix timestamp, indicates posts should be max_date this date.

		:returns: a dict created from the JSON response
		"""
		blog = blog + ".tumblr.com"

		if not max_date:
			max_date = int(time.time())

		# Store all posts in here
		all_posts = []

		# Some retries to make sure the Tumblr API actually returns everything
		retries = 0
		self.max_retries = 48 # 2 days

		# Get Tumblr posts until there's no more left.
		while True:
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while fetching blog posts from Tumblr")

			# Stop min_date 20 retries
			if retries >= self.max_retries:
				self.dataset.update_status("No more posts")
				break

			try:
				# Use the pytumblr library to make the API call
				posts = self.client.posts(blog, before=max_date, limit=20, reblog_info=True, notes_info=True, filter="raw", npf=True)
				posts = posts["posts"]

			except Exception as e:

				self.dataset.update_status("Reached the limit of the Tumblr API. Last timestamp: %s" % str(max_date))
				self.api_limit_reached = True
				break

			# Make sure the Tumblr API doesn't magically stop at an earlier date
			if not posts or isinstance(posts, str):
				retries += 1
				max_date -= 3600 # Decrease by an hour
				self.dataset.update_status("No posts returned by Tumblr - checking whether this is really all (retry %s/48)" % str(retries))
				continue

			# Append posts to main list
			else:

				# Get the lowest date
				max_date = sorted([post["timestamp"] for post in posts])[0]

				# Manually check if we have a lower date than the min date (`min_date`) already.
				# This functonality is not natively supported by Tumblr.
				if min_date:
					if max_date < min_date:

						# Get rid of all the posts that are earlier than the max_date timestamp
						posts = [post for post in posts if post["timestamp"] >= min_date]

						if posts:
							all_posts += posts
						break

				retries = 0

				all_posts += posts

			if len(all_posts) >= self.max_posts:
				self.max_posts_reached = True
				break

			self.dataset.update_status("Collected %s posts" % str(len(all_posts)))

		return all_posts

	def get_post_notes(self, blog_id, post_id):
		"""
		Gets data on the notes of a specific post.
		:param blog_id, str: The ID of the blog.
		:param post_id, str: The ID of the post.

		:returns: a list with dictionaries of notes.
		"""
		
		post_notes = []
		max_date = None

		# Do some counting
		count = 0

		# Stop trying to fetch the notes after this many retries
		max_notes_retries = 10
		notes_retries = 0

		count += 1

		if self.interrupted:
			raise ProcessorInterruptedException("Interrupted while fetching post notes from Tumblr")

		while True:

			# Requests a post's notes
			notes = self.client.notes(blog_id, id=post_id, before_timestamp=max_date)
			
			if "notes" in notes:
				notes_retries = 0

				for note in notes["notes"]:
					post_notes.append(note)

				if notes.get("_links"):
					max_date = notes["_links"]["next"]["query_params"]["before_timestamp"]

				# If there's no `_links` key, that's all.
				else:
					break

			# If there's no "notes" key in the returned dict, something might be up
			else:
				self.dataset.update_status("Couldn't get notes for Tumblr post " + str(post_id))
				notes_retries += 1
				pass

			if notes_retries > max_notes_retries:
				self.failed_notes.append(post_id)
				break

		return post_notes

	def get_post_by_id(self, blog_name, post_id):
		"""
		Fetch individual posts
		:param blog_name, str: The blog's name
		:param id, int: The post ID

		returns result list, a list with a dictionary with the post's information
		"""
		if self.interrupted:
			raise ProcessorInterruptedException("Interrupted while fetching post from Tumblr")

		connection_retries = 0

		while True:
			if connection_retries >= 5:
				self.dataset.update_status("Multiple connection refused errors; unable to continue collection of reblogs.")
				break
			try:
				# Request the specific post.
				post = self.client.posts(blog_name, id=post_id, npf=True)
		
			except ConnectionRefusedError:
				connection_retries += 1
				self.failed_reblogs.append(note["id"])
				self.dataset.update_status(f"ConnectionRefused: Unable to collect reblogs for post " + note["id"])
				continue
			
			if post:
				break

		# Tumblr API can sometimes return with this kind of error:
		# {'meta': {'status': 500, 'msg': 'Server Error'}, 'response': {'error': 'Malformed JSON or HTML was returned.'}}
		if not post or "posts" not in post:
			return None

		# Get the first element of the list - it's always one post.
		result = post["posts"][0]

		return result

	@staticmethod
	def get_tumblr_keys(user):
		config_keys = [
			config.get("api.tumblr.consumer_key", user=user),
			config.get("api.tumblr.consumer_secret", user=user),
			config.get("api.tumblr.key", user=user),
			config.get("api.tumblr.secret_key", user=user)]
		if not all(config_keys):
			raise ConfigException("Not all Tumblr API credentials are configured. Cannot query Tumblr API.")
		return config_keys

	def connect_to_tumblr(self):
		"""
		Returns a connection to the Tumblr API using the pytumblr library.

		"""
		# User input keys
		config_keys = [self.parameters.get("consumer_key"),
			self.parameters.get("consumer_secret"),
			self.parameters.get("key"),
			self.parameters.get("secret_key")]
		if not all(config_keys):
			# No user input keys; attempt to use 4CAT config keys
			config_keys = self.get_tumblr_keys(self.owner)

		self.client = pytumblr.TumblrRestClient(*config_keys)

		client_info = self.client.info()

		# Check if there's any errors
		if client_info.get("meta"):
			if client_info["meta"].get("status") == 429:
				raise ConnectionRefusedError("Tumblr API timed out")

		return self.client

	def validate_query(query, request, user):
		"""
		Validate custom data input

		Confirms that the uploaded file is a valid CSV file and, if so, returns
		some metadata.

		:param dict query:  Query parameters, from client-side.
		:param request:  	Flask request
		:param User user:  	User object of user who has submitted the query
		:return dict:  		Safe query parameters
		"""
		# no query 4 u
		if not query.get("query", "").strip():
			raise QueryParametersException("You must provide a search query.")

		# reformat queries to be a comma-separated list
		items = query.get("query").replace("#","")
		items = items.split("\n")

		# Not more than 10 plox
		if len(items) > 10:
			raise QueryParametersException("Only query for ten or less tags or blogs." + str(len(items)))

		# no query 4 u
		if not items:
			raise QueryParametersException("Search query cannot be empty.")

		# So it shows nicely in the frontend.
		items = ", ".join([item.lstrip().rstrip() for item in items if item])

		# the dates need to make sense as a range to search within
		query["min_date"], query["max_date"] = query.get("daterange")
		if any(query.get("daterange")) and not all(query.get("daterange")):
			raise QueryParametersException("When providing a date range, set both an upper and lower limit.")

		del query["daterange"]

		query["query"] = items

		# if we made it this far, the query can be executed
		return query

	@staticmethod
	def map_item(post):
		"""
		Parse Tumblr posts.
		Tumblr posts can be many different types, so some data processing is necessary.

		:param posts, list:		List of Tumblr posts as returned form the Tumblr API.
		:param reblog, bool:	Whether the post concerns a reblog of posts from the original dataset.
	
		:return dict:			Mapped item 
		"""

		media_types = ["photo", "video", "audio"]

		# We're getting info as Neue Post Format types,
		# so we need to loop through some 'blocks'.
		image_urls = []
		video_urls = []
		video_thumb_urls = []
		audio_urls = []
		audio_artists = []
		linked_urls = []
		linked_titles = []
		question = ""
		answers = ""
		raw_text = ""
		formatted_text = []
		authors_liked = []
		authors_reblogged = []
		authors_replied = []
		replies = []

		# Keep track if blocks belong to another post,
		# which is stored in `layout`.
		body_reblogged = []
		reblogged_text_blocks = []
		author_reblogged = ""
		for layout_block in post.get("layout", []):
			if layout_block["type"] == "ask":
				reblogged_text_blocks += layout_block["blocks"]
				author_reblogged = layout_block["attribution"]["blog"]["name"]

		# Loop through "blocks"
		for i, block in enumerate(post.get("content", [])):
			block_type = block["type"]

			if block_type == "image":
				image_urls.append(block["media"][0]["url"])
			elif block_type == "audio":
				audio_urls.append(block["media"]["url"])
				audio_artists.append(block["artist"])
			elif block_type == "video":
				video_urls.append(block["media"]["url"])
				if "filmstrip" in block:
					video_thumb_urls.append(block["filmstrip"]["url"])
			elif block_type == "link":
				linked_urls.append(block["url"])
				if "title" in block:
					linked_titles.append(block["title"])
				if "description" in block:
					raw_text += block["description"] + "\n"
					formatted_text.append(block["description"])
			elif block_type == "poll":
				question += block["question"]
				answers = [a["answer_text"] for a in block["answers"]]

			# We're gonna add some formatting to the text
			# Skip text that is part of a reblogged post.
			elif block_type == "text" and i not in reblogged_text_blocks:

				text = block["text"]

				extra_chars = 0
				if block.get("formatting"):
					for fmt in block["formatting"]:
						
						fmt_type = fmt["type"]
						s = fmt["start"] + extra_chars	# Start of formatted substring
						e = fmt["end"] + extra_chars	# End of formatted substring

						if fmt_type == "link":
							text = text[:s] + "[" + text[s:e] + "](" + fmt["formatting"]["url"] + ")" + text[e:]
							extra_chars += 4 + len(fmt["formatting"]["url"])
						elif fmt_type == "italic":
							text = text[:s] + "*" + text[s:e] + "*" + text[e:]
							extra_chars += 2
						elif fmt_type == "bold":
							text = text[:s] + "**" + text[s:e] + "**" + text[e:]
							extra_chars += 4

				if block.get("subtype") == "unordered-list-item":
					text = "- " + text

				raw_text += block["text"] + "\n"
				formatted_text.append(text)

			elif block_type == "text" and i in reblogged_text_blocks:
				body_reblogged.append(block["text"])

		# Add note data
		for note in post.get("notes", []):
			if note["type"] == "like":
				# Inserting at the start of the list to maintain chronological order.
				authors_liked.insert(0, note["blog_name"])
			elif note["type"] in ("posted", "reblog"):
				# If the original post is a text reblog, it will also show up in the notes.
				# We can skip these since the data is already in the main post dict.
				if note["blog_name"] != post["blog_name"] and note["timestamp"] != post["timestamp"]:
					authors_reblogged.insert(0, note["blog_name"])
			elif note["type"] == "reply":
				authors_replied.insert(0, note["blog_name"])
				replies.insert(0, note["blog_name"] + ": " + note["reply_text"])

		return MappedItem({
			"type": post["original_type"] if "original_type" in post else post["type"],
			"id": post["id"],
			"author": post["blog_name"],
			"author_avatar_url": "https://api.tumblr.com/v2/blog/" + post["blog_name"] + "/avatar",
			"thread_id": post["reblog_key"],
			"timestamp": post["timestamp"],
			"author_subject": post["blog"]["title"],
			"author_description": strip_tags(post["blog"]["description"]),
			"author_url": post["blog"]["url"],
			"author_uuid": post["blog"]["uuid"],
			"author_last_updated": post["blog"]["updated"],
			"post_url": post["post_url"],
			"post_slug": post["slug"],
			"is_reblog": True if post.get("original_type") == "note" else "",
			"body": raw_text,
			"body_markdown": "\n".join(formatted_text),
			"body_reblogged": "\n".join(body_reblogged) if body_reblogged else "",
			"author_reblogged": author_reblogged,
			"tags": ",".join(post["tags"]) if post.get("tags") else "",
			"notes": post["note_count"],
			"like_count": len(authors_liked),
			"authors_liked": ",".join(authors_liked),
			"reblog_count": len(authors_reblogged),
			"authors_reblogged": ",".join(authors_reblogged),
			"reply_count": len(authors_replied),
			"authors_replied": ",".join(authors_replied),
			"replies": "\n\n".join(replies),
			"linked_urls": ",".join(linked_urls) if linked_urls else "",
			"linked_urls_titles": "\n".join(linked_titles) if linked_titles else "",
			"image_urls": ",".join(image_urls) if image_urls else "",
			"video_urls": ",".join(video_urls) if video_urls else "",
			"video_thumb_urls": ",".join(video_thumb_urls) if video_thumb_urls else "",
			"audio_urls": ",".join(audio_urls) if audio_urls else "",
			"audio_artist": ",".join(audio_artists) if audio_artists else "",
			"poll_question": question,
			"poll_answers": ",".join(answers)
		})

	def after_process(self):
		"""
		Override of the same function in processor.py
		Used to notify of potential API errors.

		"""
		super().after_process()
		self.client = None
		errors = []
		if len(self.failed_notes) > 0:
			errors.append("API error(s) when fetching notes %s" % ", ".join(self.failed_notes))
		if len(self.failed_reblogs) > 0:
			errors.append("API error(s) when fetching reblogs %s" % ", ".join(self.failed_reblogs))
		if errors:
			self.dataset.log(";\n ".join(errors))
			self.dataset.update_status(f"Dataset completed but failed to capture some notes/reblogs; see log for details.")
