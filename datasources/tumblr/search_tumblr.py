"""
Search Tumblr via its API

Can fetch posts from specific blogs or with specific hashtags
"""

import time
import pytumblr
from requests.exceptions import ConnectionError
from datetime import datetime

import config

from backend.abstract.search import Search
from common.lib.helpers import UserInput
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException

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

	max_workers = 1
	max_retries = 3 # For API and connection retries.
	max_date_retries = 96 + 150 # For checking dates. 96 time retries of -6 hours (24 days), plus 150 extra for 150 weeks (~3 years).
	max_posts = 1000000

	max_posts_reached = False
	api_limit_reached = False

	seen_ids = set()
	failed_notes = []

	options = {
		"intro": {
			"type": UserInput.OPTION_INFO,
			"help": "Retrieve any kind of Tumblr posts with specific tags or from specific blogs. Gets 100.000 posts "
					"at max. Insert tags or names of blogs, one on each line. You may insert up to ten tags or "
					"blogs.\n\nTumblr tags may include whitespace and commas. A `#` before the tag is optional.\n\n"
					"Tag search only get posts explicitly associated with the exact tag you insert here. Querying "
					"`gogh` will thus not get posts only tagged with `van gogh`. Keyword search is unfortunately not "
					"allowed by the [Tumblr API](https://api.tumblr.com).\n\nIf 4CAT reached its Tumblr API rate "
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
		"fetch_reblogs": {
			"type": UserInput.OPTION_TOGGLE,
			"help": "Also fetch reblogs with text? (warning: slow)"
		},
		"divider": {
			"type": UserInput.OPTION_DIVIDER
		},
		"date-intro": {
			"type": UserInput.OPTION_INFO,
			"help": "**Note:** The [Tumblr API](https://api.tumblr.com) is volatile: when fetching sporadically used "
					"tags, it may return zero posts, even though older posts exist. To mitigate this, 4CAT decreases "
					"the date parameter (<code>before</code>) with six hours and sends the query again. This often "
					"successfully returns older, un-fetched posts. If it didn't find new data after 96 retries (24 "
					"days), it checks for data up to six years before the last date, decreasing 12 times by 6 months. "
					"If that also results in nothing, it assumes the dataset is complete. Check the oldest post in "
					"your dataset to see if it this is indeed the case and whether any odd time gaps exists."
		},
		"daterange": {
			"type": UserInput.OPTION_DATERANGE,
			"help": "Date range"
		}
	}

	def get_items(self, query):
		"""
		Fetches data from Tumblr via its API.

		"""

		# ready our parameters
		parameters = self.dataset.get_parameters()
		scope = parameters.get("search_scope", "")
		queries = parameters.get("query").split(", ")

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

		# for each tag or blog, get post
		for query in queries:

				# Get posts per tag
				if scope == "tag":
					new_results = self.get_posts_by_tag(query, max_date=max_date, min_date=min_date)

				# Get posts per blog
				elif scope == "blog":
					new_results, notes = self.get_posts_by_blog(query, max_date=max_date, min_date=min_date)
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
						if reblog_post:
							reblog_post = self.parse_tumblr_posts([reblog_post], reblog=True)
							results.append(reblog_post[0])
		
		self.job.finish()
		return results

	def get_posts_by_tag(self, tag, max_date=None, min_date=None):
		"""
		Get Tumblr posts posts with a certain tag
		:param tag, str: the tag you want to look for
		:param min_date: a unix timestamp, indicates posts should be min_date this date.
	    :param max_date: a unix timestamp, indicates posts should be max_date this date.

	    :returns: a dict created from the JSON response
		"""

		client = self.connect_to_tumblr()

		# Store all posts in here
		all_posts = []

		# Some retries to make sure the Tumblr API actually returns everything.
		retries = 0
		date_retries = 0

		# We're gonna change max_date, so store a copy for reference.
		max_date_original = max_date

		# We use the averag time difference between posts to spot possible gaps in the data.
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
				# Use the pytumblr library to make the API call
				posts = client.tagged(tag, before=max_date, limit=20, filter="raw")
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
					self.dataset.update_status("Couldnt add post:", check_post)
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

				posts = self.parse_tumblr_posts(posts)
				
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
		client = self.connect_to_tumblr()

		if not max_date:
			max_date = int(time.time())

		# Store all posts in here
		all_posts = []

		# Store notes here, if they exist and are requested
		all_notes = []

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
				posts = client.posts(blog, before=max_date, limit=20, reblog_info=True, notes_info=True, filter="raw")
				posts = posts["posts"]

				#if (max_date - posts[0]["timestamp"]) > 500000:
					#self.dataset.update_status("ALERT - DATES LIKELY SKIPPED")
					#self.dataset.update_status([post["timestamp"] for post in posts])

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
				# Keep the notes, if so indicated
				if self.parameters.get("fetch_reblogs"):
					for post in posts:
						if "notes" in post:
							all_notes.append(post["notes"])

				posts = self.parse_tumblr_posts(posts)

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

				#if (max_date - posts[len(posts) - 1]["timestamp"]) > 500000:
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

		max_date = None

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
				notes = client.notes(key, id=value, before_timestamp=max_date)

				if only_text_reblogs:

					if "notes" in notes:
						notes_retries = 0

						for note in notes["notes"]:
							# If it's a reblog, extract the data and save the rest of the posts for later
							if note["type"] == "reblog":
								if note.get("added_text"):
									text_reblogs.append({note["blog_name"]: note["post_id"]})

						if notes.get("_links"):
							max_date = notes["_links"]["next"]["query_params"]["before_timestamp"]

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

		# Tumblr API can sometimes return with this kind of error:
		# {'meta': {'status': 500, 'msg': 'Server Error'}, 'response': {'error': 'Malformed JSON or HTML was returned.'}}
		if "posts" not in post:
			return None

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
				self.dataset.update_status("Tumblr API timed out during query '%s', try again in 24 hours." % self.dataset.key)
				raise ConnectionRefusedError("Tumblr API timed out during query %s" % self.dataset.key)

		return client

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
		query["board"] = query.get("search_scope") + "s"  # used in web interface

		# if we made it this far, the query can be executed
		return query

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
				"tags": ",".join(post["tags"]) if post.get("tags") else None,
				"notes": post["note_count"],
				"urls": post.get("link_url"),
				"images": ",".join([photo["original_size"]["url"] for photo in post["photos"]]) if post.get("photos") else None,

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

	def after_process(self):
		"""
		Override of the same function in processor.py
		Used to notify of potential API errors.

		"""
		super().after_process()
		if len(self.failed_notes) > 0:
			self.dataset.update_status("API error(s) when fetching notes %s" % ", ".join(self.failed_notes))