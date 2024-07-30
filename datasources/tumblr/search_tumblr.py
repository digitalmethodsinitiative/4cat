"""
Search Tumblr via its API

Can fetch posts from specific blogs or with specific hashtags

For Tumblr API documentation, see https://www.tumblr.com/docs/en/api/v2
For Neue Post Format documentation, see https://github.com/tumblr/docs/blob/master/npf-spec.md

"""

import time
import pytumblr
import requests
import re
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
	failed_posts = []

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
						"at max. You may insert up to ten tags or blogs.\n\n"
						"Blog-level search also returns reblogs. *Tag-level search only returns original posts*. "
						"Reblogs of tagged posts can be retrieved via the options below.\n\n"
						"Tag search only get posts with the exact tag you insert. Querying "
						"`gogh` will thus not get posts only tagged with `van gogh`.\n\n"
						"A `#` before a tag is optional. Blog names must start with `@`.\n\n"
						"Individual posts can be retrieved through the format `@blogname:post_id`.\n\n"
						"Keyword search is not allowed by the [Tumblr API](https://api.tumblr.com).\n\n"
						"If this 4CAT reached its Tumblr API rate limit, try again 24 hours later."
			},
			"query": {
				"type": UserInput.OPTION_TEXT_LARGE,
				"help": "Tags and/or blogs",
				"tooltip": "E.g. #research tools, @4catblog, @4catblog:12347714095"
			},
			"get_notes": {
				"type": UserInput.OPTION_TOGGLE,
				"help": "Add note and reblog data (warning: slow)",
				"tooltip": "Add post and reblog note data for every post. This includes note metrics (likes, replies, reblogs), "
							"replies, and reblogged text. "
							"Blog-level search includes reblogged text by default. "
							"Enables adding reblogs as new posts",
				"default": False
			},
			"get_reblogs": {
				"type": UserInput.OPTION_TOGGLE,
				"help": "Add reblogs",
				"tooltip": "Add posts that reblogged the initial results to the dataset. "
							"Limited to 1,000 reblogs per post.",
				"requires": "get_notes==true",
				"default": False
			},
			"reblog_type": {
				"type": UserInput.OPTION_CHOICE,
				"help": "Reblogs to add",
				"options": {
					"text": "Only with added text",
					"text_or_tag": "Only with added text and/or added hashtags"
				},
				"tooltip": "What type of reblogs to add to the dataset.",
				"requires": "get_reblogs==true",
				"default": "text"
			},
			"follow_reblogs": {
				"type": UserInput.OPTION_TOGGLE,
				"help": "Add posts reblogged by collected posts",
				"tooltip": "Add all posts that were reblogged by the initial results to the dataset. "
							"This adds the entire reblog 'trail' from the initial post to the collected post. "
							"Only affects blog-level search; tag-level search only gets original posts.",
				"default": False
				},
			"reblog_outside_daterange": {
				"type": UserInput.OPTION_TOGGLE,
				"help": "Allow reblogs and reblogged posts outside of date range",
				"tooltip": "Whether to keep reblogs or reblogged posts that fall outside the optional date range limit inserted below.",
				"default": True
			}
		}

		try:
			config_keys = SearchTumblr.get_tumblr_keys(user)
		except ConfigException:
			# No 4CAT set keys for user; let user input their own
			options["key-info"] = {
				"type": UserInput.OPTION_INFO,
				"help": "To access the Tumblr API, you need to register an application. You can do so "
						"[here](https://www.tumblr.com/oauth/apps). You will first get the OAuth "
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
		queries = re.split(",|\n", parameters.get("query", ""))
		get_notes = parameters.get("get_notes", False)
		get_reblogs = parameters.get("get_reblogs", False)
		reblog_crawl_depth = parameters.get("reblog_crawl_depth", 0)
		follow_reblogs = parameters.get("follow_reblogs", False)
		reblog_type = parameters.get("reblog_type", False)
		reblog_outside_daterange = parameters.get("reblog_outside_daterange", False)

		# Store all info here
		results = []

		# Blog names and post IDs of extra posts we need to fetch
		# (e.g. in the reblog trail or posts that reblog captured posts)
		extra_posts = []

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

			query = query.strip()

			if query.startswith("@"):
				blog_name = query[1:]

				# Get a possible post ID
				post_id = None
				if ":" in query:
					blog_name, post_id = blog_name.split(":")
				new_results = self.get_posts_by_blog(blog_name, post_id=post_id, max_date=max_date, min_date=min_date)

			# Get tagged post
			else:
				if query.startswith("#"):
					query = query[1:]

				# Used for getting tagged posts, which uses requests instead.
				api_key = self.parameters.get("consumer_key")
				if not api_key:
					api_key = SearchTumblr.get_tumblr_keys(self.owner)[0]

				new_results = self.get_posts_by_tag(query, max_date=max_date, min_date=min_date, api_key=api_key)

			results += new_results

			if self.max_posts_reached:
				self.dataset.update_status("Max posts exceeded")
				break
			if self.api_limit_reached:
				self.dataset.update_status("API limit reached")
				break

		# Check for reblogged posts in the reblog trail
		if follow_reblogs:
			for result in results:
				# The post rail is stored in the trail list
				for trail_post in result.get("trail", []):
					# Some posts or blogs have been deleted; skip these
					if not "broken_blog_name" in trail_post:
						if trail_post["post_id"] not in self.seen_ids:
							extra_posts.add({"blog": trail_post["blog"], "id": trail_post["post_id"]})

		# Get note data.
		# Blog-level searches already have some note data, like reblogged text,
		# but not everything (like replies), so we're going to retrieve these here as well.
		# Also store IDs of reblogs/reblogged posts that we want to add.
		if get_notes:

			# Create a dictionary with the `reblog_key` as key and notes as value.
			# Notes are the same for all posts in a reblog chain.
			# This means that we may not have to re-query the same data.
			retrieved_notes = {}

			for i, post in enumerate(results):

				if self.max_posts_reached:
					break
				if self.api_limit_reached:
					break

				self.dataset.update_status("Retrieving notes for post %i/%i" % (i+1, len(results)))

				# We may have already encountered this note-chain
				# with a different post.
				if post["reblog_key"] in retrieved_notes:
					notes = retrieved_notes[post["reblog_key"]]

				# In the case of posts with just a few notes,
				# we may have all the possible notes in the retrieved JSON.
				elif len(post["notes"]) == post["note_count"]:
					# Add some metrics, like done in `get_notes`.
					notes = {
						"notes": post["notes"],
						"reply_count": len([n for n in notes if n["type"] == "reply"]),
						"reblog_count": len([n for n in notes if n["type"] == "reblog"]),
						"like_count": len([n for n in notes if n["type"] == "like"])
					}

				else:
					# Get notes via the API
					# Only gets first 1,000 replies/text reblogs.

					# We're using different querying modes since
					# it'll speed up the process. The fastest is 
					# `conversation`, which prioritises text reblogs and
					# replies, and also provides metrics on like and reblog counts;
					# we'll use this as default. However, if the user
					# has indicated they want to add reblogs with hashtags,
					# we'll also have to use the `reblogs_with_tags` mode.
					seen_notes = set()
					notes = self.get_notes(post["blog_name"], post["id"], mode="conversation", max_notes=1000)
					for note in notes["notes"]:
						if note["type"] == "reblog":
							seen_notes.add(note["post_id"])

					# Get tag-only reblogs; these aren't returned in `conversation` mode.
					if reblog_type == "text_or_tag":
						tag_notes = self.get_notes(post["blog_name"], post["id"], mode="reblogs_with_tags", max_notes=1000)
						for tag_note in tag_notes:
							if tag_note["post_id"] not in seen_notes:
								notes["notes"].append(tag_note)
				
				# Add to posts
				results[i] = {**results[i], **notes}
				retrieved_notes[post["reblog_key"]] = notes
				
				# Get the full data for certain reblogs and add them as new posts
				if get_reblogs:

					for note in notes["notes"]:

						# Skip replies and likes
						if note["type"] != "reblog":
							continue

						elif reblog_type == "text_or_tag":
							# Skip reblogs without tags or text
							if not note.get("tags") and not note.get("added_text"):
								continue

						elif reblog_type == "text":
							# Skip reblogs without added text
							if not note.get("added_text"):
								continue

						# Skip posts that we already collected
						if note["post_id"] in self.seen_ids:
							continue

						# Potentially skip new posts outside of the date range
						if reblog_outside_daterange and (max_date or min_date):
							if not min_date:
								if note["timestamp"] >= max_date:
									continue
							elif not min_date <= note["timestamp"] <= max_date:
								continue

						extra_posts.append({"blog": note["blog_name"], "id": note["post_id"]})

		# Add reblogged posts and reblogs to dataset
		for i, extra_post in enumerate(extra_posts):
			
			self.dataset.update_status("Adding %s/%s reblogged posts to the dataset" % (i, len(extra_posts)))

			if extra_post["id"] not in self.seen_ids:
				new_post = self.get_posts_by_blog(extra_post["blog"], extra_post["id"])

				if new_post:
					new_post = new_post[0]

					# Add note data; these should already be retrieved above
					if get_notes:
						new_post = {**new_post, **retrieved_notes[new_post["reblog_key"]]}

					results.append(new_post)
					self.seen_ids.add(extra_post["id"])

		self.job.finish()
		return results

	def get_posts_by_tag(self, tag, max_date=None, min_date=None, api_key=None):
		"""
		Get Tumblr posts posts with a certain tag.
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
				self.update_status("Encountered a connection error, waiting 10 seconds")
				time.sleep(10)
				retries += 1
				continue

			# Skip posts that we already enountered,
			# preventing Tumblr API shenanigans or double posts because of
			# time reductions. Make sure it's no error string, though.
			new_posts = []
			for post in posts:
				# Sometimes the API repsonds just with "meta", "response", or "errors".
				if isinstance(post, str):
					self.dataset.update_status("Couldn't add post:", post)
					retries += 1
					break
				else:
					retries = 0
					if post["id"] not in self.seen_ids:
						self.seen_ids.add(post["id"])
						new_posts.append(post)

			posts = new_posts

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

			# Make sure the Tumblr API doesn't magically stop even if earlier posts are available
			if not posts:

				date_retries += 1

				# We're first gonna check carefully if there's small timegaps by
				# decreasing by six hours.
				# If that didn't result in any new posts, also dedicate 12 date_retries
				# with reductions of six months, just to be sure there's no data from
				# years earlier missing.

				if date_retries < 96:
					max_date -= 21600 # Decrease by six hours
				elif date_retries <= self.max_date_retries:
					max_date -= 604800 # Decrease by one week
					self.dataset.update_status("No new posts found for #%s - looking for posts before %s" % (tag, datetime.fromtimestamp(max_date).strftime("%Y-%m-%d %H:%M:%S")))

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
						posts = [post for post in posts if post["timestamp"] >= date]
						if posts:
							all_posts += posts

						max_date = date
						break

					time_difs.append(time_dif)

				# Stop if we found nothing for this query
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
						break

				# We got a new post, so we can reset the retry counts.
				date_retries = 0
				retries = 0

				# Add retrieved posts top the main list
				all_posts += posts

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

			self.dataset.update_status("Collected %s posts for #%s, retrieving posts before %s" % (str(len(all_posts)), tag, max_date_str,))
			time.sleep(.2)

		return all_posts

	def get_posts_by_blog(self, blog, post_id=None, max_date=None, min_date=None):
		"""
		Get Tumblr posts from a certain blog
		:param blog, str: the name of the blog you want to look for
		:param post_id, str:	the post ID (optional)
		:param max_date: a unix timestamp, indicates posts should be max_date this date.
		:param min_date: a unix timestamp, indicates posts should be min_date this date.

		:returns: a dict created from the JSON response
		"""

		blog = blog + ".tumblr.com"

		if post_id:
			try:
				test_id = int(post_id)
			except TypeError:
				raise QueryParametersException("Post ID %s is invalid" % post_id)

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
				posts = self.client.posts(blog, id=post_id, before=max_date, limit=20, reblog_info=True, notes_info=True, filter="raw", npf=True)
				posts = posts["posts"]

			except ConnectionRefusedError:
				retries += 1
				if post_id:
					self.failed_posts.append(post_id)
					self.dataset.update_status("ConnectionRefused: Unable to collect post %s/%s" % (blog, post_id))
				else:
					self.dataset.update_status("ConnectionRefused: Unable to collect posts for blog %s before %s" % (blog, max_date))
				time.sleep(10)
				continue

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

			# Skip posts that we already enountered,
			# preventing Tumblr API shenanigans or double posts because of
			# time reductions. Make sure it's no error string, though.
			new_posts = []
			for post in posts:
				# Sometimes the API repsonds just with "meta", "response", or "errors".
				if isinstance(post, str):
					self.dataset.update_status("Couldn't add post:", post)
					retries += 1
					break
				else:
					retries = 0
					if post["id"] not in self.seen_ids:
						self.seen_ids.add(post["id"])
						new_posts.append(post)

			posts = new_posts

			if not post_id:

				# Append posts to main list
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
			if post_id:
				break

			self.dataset.update_status("Collected %s posts for blog %s" % (str(len(all_posts)), blog))
			time.sleep(.2)

		return all_posts

	def get_notes(self, blog_id, post_id, mode="conversation", max_notes=1000):
		"""
		Gets data on the notes of a specific post.
		:param blog_id, str: 	The ID of the blog.
		:param post_id, str:	The ID of the post.
		:param mode, str:		The type of notes that get priority.
								`conversation` prioritises text reblogs and replies.
		:param mode, max_notes:	Maximum amount of notes to return.

		:returns: a list with dictionaries of notes.
		"""
		
		note_metrics = {}
		post_notes = []
		max_date = None

		# Do some counting
		count = 0

		# Some posts have tens of thousands of notes
		# so we'll cap this at 100

		# Stop trying to fetch the notes after this many retries
		max_notes_retries = 10
		notes_retries = 0

		first_batch = True
		note_metrics = {}

		if self.interrupted:
			raise ProcessorInterruptedException("Interrupted while fetching post notes from Tumblr")

		while True:

			if notes_retries >= max_notes_retries:
				self.dataset.update_status("Too many connection errors; unable to collect notes for post %s" % post_id)
				self.failed_posts.append(post_id)
				break

			# Request a post's notes
			try:

				# Important: we're getting notes in 'conversation' mode to
				# prioritise replies and reblogs that add text.
				# We're not interested in the the names of authors that liked the post
				# or who reblogged without adding content.
				notes = self.client.notes(blog_id, id=post_id, before_timestamp=max_date, mode=mode)
			except ConnectionRefusedError:
				self.dataset.update_status("Couldn't get notes for post %s (ConnectionRefusedError), trying again" % post_id)
				notes_retries += 1
				time.sleep(10)
				continue

			except Exception as e:
				# Stop with unknown errors
				self.dataset.update_status("Couldn't get notes for post %s. Unknown error: %s" % (post_id, e))
				notes_retries += 1
				break

			if "notes" in notes:
				notes_retries = 0

				# Add some metrics for the first response
				if first_batch and mode == "conversation":
					note_metrics = {
						"note_count": notes["total_notes"],
						"reblog_count": notes["total_reblogs"],
						"like_count": notes["total_likes"],
						"reply_count": 0
					}
					first_batch = False

				# Add notes
				for note in notes["notes"]:
					if mode == "conversation" and note["type"] == "reply":
						note_metrics["reply_count"] += 1

					count += 1
					post_notes.append(note)

				# `conversation` mode groups likes and reblogs without commentary
				# in the `rollup_notes` list. We're adding reblogs to the post notes.
				if mode == "conversation":
					if "rollup_notes" in notes and "notes" in notes["rollup_notes"][0]:
						for note in notes["rollup_notes"][0]["notes"]:
							if note["type"] == "reblog":
								count += 1
								post_notes.append(note)

				if count >= max_notes:
					break

				if notes.get("_links"):
					max_date = notes["_links"]["next"]["query_params"]["before_timestamp"]
					self.dataset.update_status("Added %s notes for post %s:%s" % (count, blog_id, post_id))
					time.sleep(.2)

				# If there's no `_links` key, that's all.
				else:
					break

			# If there's no "notes" key in the returned dict, something might be up
			else:
				notes_retries += 1
				time.sleep(1)
				continue

		# Merge notes and note metrics
		post_notes = {"notes": post_notes, **note_metrics}

		return post_notes

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

		try:
			client_info = self.client.info()
		except Exception as e:
			raise ConnectionRefusedError("Couldn't connect to Tumblr API, (%s)" % e)

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
	
		:return dict:			Mapped item 
		"""

		media_types = ["photo", "video", "audio"]
		image_urls = []
		video_urls = []
		video_thumb_urls = []
		audio_urls = []
		audio_artists = []
		link_urls = []
		link_titles = []
		link_descriptions = []
		question = ""
		answers = ""
		raw_text = []
		formatted_text = []
		authors_reblogged = []
		reblog_trail = []
		body_reblogged = []
		reblog_trail = []
		body_ask = []
		author_ask = ""
		authors_replied = []
		like_count = ""
		replies = []
		unknown_blocks = []

		ordered_list_count = 1

		# Sometimes the content order is reshuffled in the `layout` property,
		# so we have to follow this.
		content_order = []
		blocks = []
		if post.get("layout"):
			if "type" in post["layout"][0]:
				if post["layout"][0]["type"] == "rows":
					for display in post["layout"][0].get("display", []):
						content_order.append(display["blocks"][0])
		if not content_order:
			content_order = range(len(post["content"]))

		# Some text blocks are 'ask' blocks
		ask_blocks = []
		for layout_block in post.get("layout", []):
			if layout_block["type"] == "ask":
				ask_blocks += layout_block["blocks"]
				author_ask = layout_block["attribution"]["blog"]["name"]

		# We're getting info as Neue Post Format types,
		# so we need to loop through and join some content 'blocks'.
		for i in content_order:
			
			block = post["content"][i]
			block_type = block["type"]

			# Image
			if block_type == "image":
				image_urls.append(block["media"][0]["url"])
			# Audio file
			elif block_type == "audio":
				audio_urls.append(block["url"] if "url" in block else block["media"]["url"])
				audio_artists.append(block.get("artist", ""))
			# Video (embedded or hosted)
			elif block_type == "video":
				if "media" in block:
					video_urls.append(block["media"]["url"])
				elif "url" in block:
					video_urls.append(block["url"])
				if "filmstrip" in block:
					video_thumb_urls.append(block["filmstrip"]["url"])
				elif "poster" in block:
					video_thumb_urls.append(block["poster"][0]["url"])
				else:
					video_thumb_urls.append("")

			# Embedded link
			elif block_type == "link":
				link_urls.append(block["url"])
				if "title" in block:
					link_titles.append(block["title"])
				if "description" in block:
					link_descriptions.append(block["description"])
			# Poll
			elif block_type == "poll":
				# Only one poll can be added per post
				question = block["question"]
				answers = ",".join([a["answer_text"] for a in block["answers"]])

			# Text; we're adding Markdown formatting.
			elif block_type == "text":

				md_text = SearchTumblr.format_tumblr_text(block)

				# If it's an ask text, we're storing it in
				# a different column
				if i in ask_blocks:
					block_type = "ask"
					body_ask.append(block["text"])
				else:
					raw_text.append(block["text"])
					formatted_text.append(md_text)

			# Unknown block; can be a third-party app
			else:
				unknown_blocks.append(json.dumps(block))

			blocks.append(block_type)

		# Parse some note
		for note in post.get("notes", []):
			if note["type"] == "reply":
				authors_replied.insert(0, note["blog_name"])
				replies.insert(0, note["reply_text"])

		# The API sometimes gives back a 'trail' of reblogged content
		# This includes reblogged content, but it's not entirely complete (e.g. no hashtags)
		# so we'll only store the original blog name and its text content.
		for i, reblog in enumerate(post.get("trail", [])):
			
			reblogged_text = []

			if "broken_blog_name" in reblog:
				reblog_author = reblog["broken_blog_name"]
			else:
				reblog_author = reblog["blog"]["name"]
			
			for reblog_block in reblog.get("content", []):
				if reblog_block["type"] == "text":
					reblogged_text.append(reblog_block["text"])

			if not reblogged_text:
				reblogged_text = ""
			body_reblogged.append("\n".join(reblogged_text))
			
			reblog_trail.append(reblog_author)

		return MappedItem({
			"type": post["original_type"] if "original_type" in post else post["type"],
			"id": post["id"] if "id" in post else post["post"]["id"],
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
			"is_reblog": True if post.get("parent_post_url") else "",
			"reblog_key": post["reblog_key"],
			"body": "\n".join(raw_text),
			"body_markdown": "\n".join(formatted_text),
			"body_reblogged": "\n\n".join(body_reblogged),
			"reblog_trail": ",".join(reblog_trail),
			"parent_post_url": post.get("parent_post_url", ""),
			"body_ask": "\n".join(body_ask),
			"author_ask": author_ask,
			"content_order": ",".join(blocks),
			"tags": ",".join(post.get("tags", "")),
			"note_count": post["note_count"],
			"reblog_count": post.get("reblog_count", ""),
			"like_count": post.get("like_count", ""),
			"reply_count": post.get("reply_count", ""),
			"authors_replied": ",".join(authors_replied),
			"replies": "\n\n".join(replies),
			"link_urls": ",".join(link_urls),
			"link_titles": "\n".join(link_titles),
			"link_descriptions": "\n".join(link_descriptions),
			"image_urls": ",".join(image_urls),
			"video_urls": ",".join(video_urls),
			"video_thumb_urls": ",".join(video_thumb_urls),
			"audio_urls": ",".join(audio_urls),
			"audio_artist": ",".join(audio_artists),
			"poll_question": question,
			"poll_answers": answers,
			"unknown_blocks": "\n".join(unknown_blocks)
		})

	@staticmethod
	def format_tumblr_text(text_content):
		"""
		Format text content according to Tumblr's Neue Post Format definition.
		Returns text as mardkown.

		:param content, list:	The list of content as returned by the Tumblr API (can also be part of a `trail`)
		:returns dict

		"""

		text = text_content["text"]

		if text_content.get("formatting"):

			# Dict with index numbers as keys where inserts need to be made,
			# and the replacement strings as values. Done this way so we know
			# when multiple formatting operations need to be made at the same
			# index position.
			insert_indexes = set()
			inserts = {}

			for fmt in text_content["formatting"]:
				fmt_type = fmt["type"]
				if fmt["type"] in ("link", "bold", "italic"):
					s = fmt["start"]
					e = fmt["end"]

					opening = True # To know if styles need to be appended or prepended
					for n in [s, e]:
						insert_indexes.add(n)
						n = str(n)
						if n not in inserts:
							inserts[n] = ""
						if fmt_type == "link" and opening:
							inserts[n] = inserts[n] + "["
						elif fmt_type == "link" and not opening:
							inserts[n] = "](" + fmt["url"] + ")" + inserts[n]
						elif fmt_type == "italic":
							inserts[n] = "*" + inserts[n] if opening else inserts[n] + "*"
						elif fmt_type == "bold":
							inserts[n] = "**" + inserts[n] if opening else inserts[n] + "**"
						opening = False

			# Change text
			if inserts:
				extra_chars = 0
				for n, insert in inserts.items():
					n = int(n) + extra_chars
					text = text[:n] + insert + text[n:]
					extra_chars += len(insert)
		
		# Some more 'subtype' formatting
		subtype = text_content.get("subtype")
		if subtype:
			if subtype == "unordered-list-item":
				text = "- " + text
			if subtype == "ordered-list-item":
				text = str(ordered_list_count) + ". " + text
				ordered_list_count += 1
			elif subtype == "heading1":
				text = "#" + text
			elif subtype == "heading2":
				text = "##" + text
			elif subtype == "quote":
				text = ">" + text
			elif subtype == "indented":
				text = "  " + text

		return text

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
		if len(self.failed_posts) > 0:
			errors.append("API error(s) when fetching reblogs %s" % ", ".join(self.failed_posts))
		if errors:
			self.dataset.log(";\n ".join(errors))
			self.dataset.update_status(f"Dataset completed but failed to capture some notes/reblogs; see log for details")
