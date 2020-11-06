"""
Search Tumblr via its API

Can fetch posts from specific blogs or with specific hashtags
"""

import shutil
import os
import re
import time
import pytumblr
import datetime

import config

from backend.abstract.search import Search
from backend.lib.exceptions import QueryParametersException, ProcessorInterruptedException

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
	extension = "csv"  # extension of result file, used internally and in UI

	# not available as a processor for existing datasets
	accepts = [None]

	# let's not get rate limited
	max_workers = 1
	max_retries = 3
	max_posts = 1000000

	max_posts_reached = False
	api_limit_reached = False

	failed_notes = []

	def get_posts_simple(self, query):
		"""
		Fetches data from Tumblr via its API.

		"""

		# ready our parameters
		parameters = self.dataset.get_parameters()
		scope = parameters.get("search_scope", "")
		queries = parameters.get("query")

		# Store all info here
		results = []

		# Store all notes from posts by blogs here
		all_notes = []

		# Get date parameters
		after = parameters.get("after", None)
		before = parameters.get("before", None)

		# for each tag or blog, get post
		for query in queries:

				# Get posts per tag
				if scope == "tag":
					new_results = self.get_posts_by_tag(query, before=before, after=after)
				# Get posts per blog
				elif scope == "blog":
					new_results, notes = self.get_posts_by_blog(query, before=before, after=after)
					all_notes.append(notes)
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

		# If we also want the posts that reblogged the fetched posts:
		if parameters.get("fetch_reblogs") and not self.max_posts_reached and not self.api_limit_reached:
			self.dataset.update_status("Getting notes from all posts")

			# Reblog information is already returned for blog-level searches
			if scope == "blog":
				text_reblogs = []

				# Loop through and add the text reblogs that came with the results.
				for post_notes in all_notes:
					print(post_notes)
					for post_note in post_notes:
						for note in post_note:
							if note["type"] == "reblog":
								text_reblogs.append({note["blog_name"]: note["post_id"]})

			# Retrieving notes for tag-based posts should be done one-by-one.
			# Fetching them all at once is not supported by the Tumblr API.
			elif scope == "tag":
				# Prepare dicts to pass to `get_post_notes`
				posts_to_fetch = {result["author"]: result["id"] for result in results}

				# First extract the notes of each post, and only keep text reblogs
				text_reblogs = self.get_post_notes(posts_to_fetch)

			# Get the full data for text reblogs.
			if text_reblogs:

				for i, text_reblog in enumerate(text_reblogs):
					self.dataset.update_status("Got %i/%i text reblogs" % (i, len(text_reblogs)))
					for key, value in text_reblog.items():
						reblog_post = self.get_post_by_id(key, value)
						reblog_post = self.parse_tumblr_posts([reblog_post], reblog=True)
						results.append(reblog_post[0])

		self.job.finish()
		return results

	def get_posts_by_tag(self, tag, before=None, after=None):
		"""
		Get Tumblr posts posts with a certain tag
		:param tag, str: the tag you want to look for
		:param after: a unix timestamp, indicates posts should be after this date.
	    :param before: a unix timestamp, indicates posts should be before this date.

	    :returns: a dict created from the JSON response
		"""

		client = self.connect_to_tumblr()

		if not before:
			before = int(time.time())

		# Store all posts in here
		all_posts = []

		# Some retries to make sure the Tumblr API actually returns everything
		retries = 0
		max_retries = 48 # 2 days

		# Get Tumblr posts until there's no more left.
		while True:
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while fetching tag posts from Tumblr")

			# Stop after 20 retries
			if retries >= max_retries:
				self.dataset.update_status("No more posts")
				break

			try:
				# Use the pytumblr library to make the API call
				posts = client.tagged(tag, before=before, limit=20, filter="raw")

				#if (before - posts[0]["timestamp"]) > 500000:
					#self.dataset.update_status("ALERT - DATES LIKELY SKIPPED")
					#self.dataset.update_status([post["timestamp"] for post in posts])

			except Exception as e:

				self.dataset.update_status("Reached the limit of the Tumblr API. Last timestamp: %s" % str(before))
				self.api_limit_reached = True
				break

			# Make sure the Tumblr API doesn't magically stop at an earlier date
			if not posts or isinstance(posts, str):
				retries += 1
				before -= 3600 # Decrease by an hour
				self.dataset.update_status("No posts - querying again but an hour earlier (retry %s/48)" % str(retries))
				continue

			# Append posts to main list
			else:
				posts = self.parse_tumblr_posts(posts)

				before = posts[len(posts) - 1]["timestamp"]

				# manually check if we've reached the `after` already (not natively supported by Tumblr)
				if after:
					if before <= after:
						# Get rid of all the posts that are earlier than the before timestamp
						posts = [post for post in posts if post["timestamp"] > after]

						if posts:
							all_posts += posts
						break

				all_posts += posts
				retries = 0

				#if (before - posts[len(posts) - 1]["timestamp"]) > 500000:
					#self.dataset.update_status("ALERT - DATES LIKELY SKIPPED")
					#self.dataset.update_status([post["timestamp"] for post in posts])


			if len(all_posts) >= self.max_posts:
				self.max_posts_reached = True
				break

			self.dataset.update_status("Collected %s posts" % str(len(all_posts)))

		return all_posts

	def get_posts_by_blog(self, blog, before=None, after=None):
		"""
		Get Tumblr posts posts with a certain blog
		:param tag, str: the name of the blog you want to look for
		:param after: a unix timestamp, indicates posts should be after this date.
	    :param before: a unix timestamp, indicates posts should be before this date.

	    :returns: a dict created from the JSON response
		"""

		blog = blog + ".tumblr.com"
		client = self.connect_to_tumblr()

		if not before:
			before = int(time.time())

		# Store all posts in here
		all_posts = []

		# Store notes here, if they exist and are requested
		all_notes = []

		# Some retries to make sure the Tumblr API actually returns everything
		retries = 0
		max_retries = 48 # 2 days

		# Get Tumblr posts until there's no more left.
		while True:
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while fetching blog posts from Tumblr")

			# Stop after 20 retries
			if retries >= max_retries:
				self.dataset.update_status("No more posts")
				break

			try:
				# Use the pytumblr library to make the API call
				posts = client.posts(blog, before=before, limit=20, reblog_info=True, notes_info=True, filter="raw")
				posts = posts["posts"]

				#if (before - posts[0]["timestamp"]) > 500000:
					#self.dataset.update_status("ALERT - DATES LIKELY SKIPPED")
					#self.dataset.update_status([post["timestamp"] for post in posts])

			except Exception as e:

				self.dataset.update_status("Reached the limit of the Tumblr API. Last timestamp: %s" % str(before))
				self.api_limit_reached = True
				break

			# Make sure the Tumblr API doesn't magically stop at an earlier date
			if not posts or isinstance(posts, str):
				retries += 1
				before -= 3600 # Decrease by an hour
				self.dataset.update_status("No posts - querying again but an hour earlier (retry %s/48)" % str(retries))
				continue

			# Append posts to main list
			else:
				# Keep the notes, if so indicated
				if self.parameters.get("fetch_reblogs"):
					for post in posts:
						if "notes" in post:
							all_notes.append(post["notes"])

				posts = self.parse_tumblr_posts(posts)

				before = posts[len(posts) - 1]["timestamp"]

				# manually check if we've reached the `after` already (not natively supported by Tumblr)
				if after:
					if before <= after:
						# Get rid of all the posts that are earlier than the before timestamp
						posts = [post for post in posts if post["timestamp"] > after]

						if posts:
							all_posts += posts
						break

				all_posts += posts
				retries = 0

				#if (before - posts[len(posts) - 1]["timestamp"]) > 500000:
					#self.dataset.update_status("ALERT - DATES LIKELY SKIPPED")
					#self.dataset.update_status([post["timestamp"] for post in posts])

			if len(all_posts) >= self.max_posts:
				self.max_posts_reached = True
				break

			self.dataset.update_status("Collected %s posts" % str(len(all_posts)))

		return all_posts, all_notes

	def get_post_notes(self, di_blogs_ids, only_text_reblogs=True):
		"""
		Gets the post notes.
		:param di_blogs_ids, dict: A dictionary with blog names as keys and post IDs as values.
		:param only_text_reblogs, bool: Whether to only keep notes that are text reblogs.
		"""

		client = self.connect_to_tumblr()

		# List of dict to get reblogs. Items are: [{"blog_name": post_id}]
		text_reblogs = []

		before = None

		# Do some counting
		len_blogs = len(di_blogs_ids)
		count = 0

		# Stop trying to fetch the notes after this many retries
		max_notes_retries = 10
		notes_retries = 0

		for key, value in di_blogs_ids.items():

			count += 1

			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while fetching post notes from Tumblr")

			# First, get the blog names and post_ids from reblogs
			# Keep digging till there's nothing left, or if we can fetch no new notes
			while True:

				# Requests a post's notes
				notes = client.notes(key, id=value, before_timestamp=before)

				if only_text_reblogs:

					if "notes" in notes:
						notes_retries = 0

						for note in notes["notes"]:
							# If it's a reblog, extract the data and save the rest of the posts for later
							if note["type"] == "reblog":
								if note.get("added_text"):
									text_reblogs.append({note["blog_name"]: note["post_id"]})

						if notes.get("_links"):
							before = notes["_links"]["next"]["query_params"]["before_timestamp"]

						# If there's no `_links` key, that's all.
						else:
							break

					# If there's no "notes" key in the returned dict, something might be up
					else:
						self.log.update_status("Couldn't get notes for Tumblr request " + str(notes))
						notes_retries += 1
						pass

					if notes_retries > max_notes_retries:
						self.failed_notes.append(key)
						break

			self.dataset.update_status("Identified %i text reblogs in %i/%i notes" % (len(text_reblogs), count, len_blogs))

		return text_reblogs

	def get_post_by_id(self, blog_name, post_id):
		"""
		Fetch individual posts
		:param blog_name, str: The blog's name
		:param id, int: The post ID

		returns result list, a list with a dictionary with the post's information
		"""
		if self.interrupted:
			raise ProcessorInterruptedException("Interrupted while fetching post from Tumblr")

		client = self.connect_to_tumblr()

		# Request the specific post.
		post = client.posts(blog_name, id=post_id)

		# Get the first element of the list - it's always one post.
		result = post["posts"][0]

		return result

	def connect_to_tumblr(self):
		"""
		Returns a connection to the Tumblr API using the pytumblr library.

		"""
		client = pytumblr.TumblrRestClient(
			config.TUMBLR_CONSUMER_KEY,
			config.TUMBLR_CONSUMER_SECRET_KEY,
			config.TUMBLR_API_KEY,
			config.TUMBLR_API_SECRET_KEY
		)
		client_info = client.info()

		# Check if there's any errors
		if client_info.get("meta"):
			if client_info["meta"].get("status") == 429:
				self.log.info("Tumblr API timed out during query %s" % self.dataset.key)
				self.dataset.update_status("Tumblr API timed out during query '%s', try again in 24 hours." % query)
				raise ConnectionRefusedError("Tumblr API timed out during query %s" % self.dataset.key)

		return client

	def validate_query(query, request, user):
		"""
		Validate custom data input

		Confirms that the uploaded file is a valid CSV file and, if so, returns
		some metadata.

		:param dict query:  Query parameters, from client-side.
		:param request:  Flask request
		:param User user:  User object of user who has submitted the query
		:return dict:  Safe query parameters
		"""

		# 'location' would be possible as well but apparently requires a login
		if query.get("search_scope", "") not in ("tag", "blog"):
			raise QueryParametersException("Invalid search scope: must be tag or blog")

		# no query 4 u
		if not query.get("query", "").strip():
			raise QueryParametersException("You must provide a search query.")

		# reformat queries to be a comma-separated list
		items = query.get("query").replace("\n", ",").replace("#","").replace("\r", ",")
		items = items.split(",")
		items = [item.lstrip().rstrip() for item in items if item]

		print(query.get("max_date"), query.get("min_date"))

		# Set dates, if given.
		if query.get("max_date") or query.get("min_date"):

			# On some OSes, the date is submitted as dd-mm-yyyy. Make sure to also fetch these.
			ddmmyyyy = r"^([0-2][0-9]|(3)[0-1])(-)(((0)[0-9])|((1)[0-2]))(-)\d{4}$"
			date_format = "%Y-%m-%d"

			# Before
			if query.get("max_date"):
				try:
					if re.match(ddmmyyyy, query.get("max_date","")):
						date_format = "%d-%m-%Y"
					before = int(datetime.datetime.strptime(query.get("max_date", ""), date_format).timestamp())
				except ValueError:
					raise QueryParametersException("Invalid value for max date %s " % str(query.get("max_date")))
			else:
				before = None

			# After
			if query.get("min_date"):
				date_format = "%Y-%m-%d"
				try:
					if re.match(ddmmyyyy, query.get("min_date","")):
						date_format = "%d-%m-%Y"
					after = int(datetime.datetime.strptime(query.get("min_date", ""), date_format).timestamp())
				except ValueError:
					raise QueryParametersException("Invalid value for min date %s " % str(query.get("min_date")))
			else:
				after = None
		else:
			before = None
			after = None

		# Not more than 5 plox
		if len(items) > 5:
			raise QueryParametersException("Only query for five or less tags or blogs.")
		# no query 4 u
		if not items:
			raise QueryParametersException("Invalid search search query.")

		# simple!
		return {
			"query": items,
			"board": query.get("search_scope") + "s",  # used in web interface
			"search_scope": query.get("search_scope"),
			"fetch_reblogs": bool(query.get("fetch_reblogs", False)),
			"before": before,
			"after": after
		}

	def parse_tumblr_posts(self, posts, reblog=False):
		"""
		Function to parse Tumblr posts into the same dict items.
		Tumblr posts can be many different types, so some data processing is necessary.

		:param posts, list: List of Tumblr posts as returned form the Tumblr API.
		:param reblog, bool: Whether the post concerns a reblog of posts from the original dataset.

		returns list processed_posts, a list with dictionary items of post info.
		"""

		# Store processed posts here
		processed_posts = []

		media_tags = ["photo", "video", "audio"]

		# Loop through all the posts and write a row for each of them.
		for post in posts:
			post_type = post["type"]

			# The post's text is in different keys depending on the post type
			if post_type in media_tags:
				text = post["caption"]
			elif post_type == "link":
				text = post["description"]
			elif post_type == "text" or post_type == "chat":
				text = post["body"]
			elif post_type == "answer":
				text = post["question"] + "\n" + post["answer"]
			else:
				text = ""

			# Different options for video types (YouTube- or Tumblr-hosted)
			if post_type == "video":

				video_source = post["video_type"]
				# Use `get` since some videos are deleted
				video_url = post.get("permalink_url")

				if video_source == "youtube":
					# There's no URL if the YouTube video is deleted
					if video_url:
						video_id = post["video"]["youtube"]["video_id"]
					else:
						video_id = "deleted"
				else:
					video_id = "unknown"

			else:
				video_source = None
				video_id = None
				video_url = None

			# All the fields to write
			processed_post = {
				# General columns
				"type": post_type,
				"timestamp_full": post["date"],
				"timestamp": post["timestamp"],
				"is_reblog": reblog,

				# Blog columns
				"author": post["blog_name"],
				"subject": post["blog"]["title"],
				"blog_description": post["blog"]["description"],
				"blog_url": post["blog"]["url"],
				"blog_uuid": post["blog"]["uuid"],
				"blog_last_updated": post["blog"]["updated"],

				# Post columns
				"id": post["id"],
				"post_url": post["post_url"],
				"post_slug": post["slug"],
				"thread_id": post["reblog_key"],
				"body": text.replace("\x00", ""),
				"tags": post.get("tags"),
				"notes": post["note_count"],
				"urls": post.get("link_url"),
				"images": [photo["original_size"]["url"] for photo in post["photos"]] if post.get("photos") else None,

				# Optional video columns
				"video_source": video_source if post_type == "video" else None,
				"video_url": video_url if post_type == "video" else None,
				"video_id": video_id if post_type == "video" else None,
				"video_thumb": post.get("thumbnail_url"), # Can be deleted

				# Optional audio columns
				"audio_type": post.get("audio_type"),
				"audio_url": post.get("audio_source_url"),
				"audio_plays": post.get("plays"),

				# Optional link columns
				"link_author": post.get("link_author"),
				"link_publisher": post.get("publisher"),
				"link_image": post.get("link_image"),

				# Optional answers columns
				"asking_name": post.get("asking_name"),
				"asking_url": post.get("asking_url"),
				"question": post.get("question"),
				"answer": post.get("answer"),

				# Optional chat columns
				"chat": post.get("dialogue")
			}

			# Store the processed post
			processed_posts.append(processed_post)

		return processed_posts

	def get_search_mode(self, query):
		"""
		Tumblr searches are always simple

		:return str:
		"""
		return "simple"

	def get_posts_complex(self, query):
		"""
		Complex post fetching is not used by the Tumblr datasource

		:param query:
		:return:
		"""
		pass

	def fetch_posts(self, post_ids, where=None, replacements=None):
		"""
		Posts are fetched via instaloader for this datasource
		:param post_ids:
		:param where:
		:param replacements:
		:return:
		"""
		pass

	def fetch_threads(self, thread_ids):
		"""
		Thread filtering is not a toggle for Tumblr datasets

		:param thread_ids:
		:return:
		"""
		pass

	def get_thread_sizes(self, thread_ids, min_length):
		"""
		Thread filtering is not a toggle for Tumblr datasets

		:param tuple thread_ids:
		:param int min_length:
		results
		:return dict:
		"""
		pass

	def after_process(self):
		"""
		Override of the same function in processor.py
		Used to notify of potential API errors.

		"""
		super().after_process()
		if len(self.failed_notes) > 0:
			self.dataset.update_status("API error(s) when fetching notes %s" % ", ".join(self.failed_notes))