"""
Search Tumblr via its API

Can fetch posts from specific blogs or with specific hashtags
"""

import shutil
import os
import re
import time
import pytumblr

from backend.abstract.search import Search
from backend.lib.exceptions import QueryParametersException


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

	def get_posts_simple(self, query):
		"""
		Fetches data from Tumblr via its API.
		"""
		

		# this is useful to include in the results because researchers are
		# always thirsty for them hashtags
		hashtag = re.compile(r"#([^\s,.+=-]+)")
		mention = re.compile(r"@([a-zA-Z0-9_]+)")

		# reserve a folder for temporary downloaded data
		# working_directory = self.dataset.get_temporary_path()
		# working_directory.mkdir()
		# os.chdir(working_directory)

		# ready our parameters
		parameters = self.dataset.get_parameters()
		scope = parameters.get("search_scope", "")
		queries = [query.strip() for query in parameters.get("query", "").split(",")]

		# for each query, get items
		for query in queries:
			results = self.get_posts_by_tag(query, before=parameters.get("before"))

		# remove temporary fetched data and return posts
		# shutil.rmtree(working_directory)

		print(results)
		self.job.finish()
		return results

	def get_posts_by_tag(self, tag, before=None):
		"""
		Get Tumblr posts posts with a certain tag
		:param tag, str: the tag you want to look for
		:param after: a unix timestamp, indicates posts should be after this date.
	    :param before: a unix timestamp, , indicates posts should be before this date.

	    :returns: a dict created from the JSON response
		"""

		# Connect to the Tumblr API
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
				self.dataset.update_status("Tumblr API timed out during query '%s'" % query)

		if not before:
			before = int(time.time())
		
		# Store all posts in here
		all_posts = []

		# Get Tumblr posts until there's no more left.
		while True:

			# Use the pytumblr library to make the API call
			posts = client.tagged(tag, before=before, limit=20, filter="raw")

			# Nothing left to do?
			if not posts:
				print("No posts with tag left.")
				break

			else: # Append posts to main list
				posts = self.parse_tumblr_posts(posts)
				for one_post in posts:
					all_posts.append(one_post)

			before = posts[len(posts) - 1]["timestamp"]
			
			self.dataset.update_status("Collected %s posts" % str(len(posts)))

			# Wait a bit to stay friends with the bouncer
			time.sleep(3)

		return all_posts

	def validate_query(query, request):
		"""
		Validate custom data input

		Confirms that the uploaded file is a valid CSV file and, if so, returns
		some metadata.

		:param dict query:  Query parameters, from client-side.
		:param request:  Flask request
		:return dict:  Safe query parameters
		"""

		# 'location' would be possible as well but apparently requires a login
		if query.get("search_scope", "") not in ("hashtag", "blog"):
			raise QueryParametersException("Invalid search scope: must be hashtag or blog")

		# no query 4 u
		if not query.get("query", "").strip():
			raise QueryParametersException("You must provide a search query.")

		# 500 is mostly arbitrary - may need tweaking
		max_posts = 2500
		if query.get("max_posts", ""):
			try:
				max_posts = min(abs(int(query.get("max_posts"))), max_posts)
			except TypeError:
				raise QueryParametersException("Provide a valid number of posts to query.")

		# reformat queries to be a comma-separated list
		items = query.get("query").replace("\n", ",")

		# simple!
		return {
			"items": max_posts,
			"query": items,
			"board": query.get("search_scope") + "s",  # used in web interface
			"search_scope": query.get("search_scope"),
			"scrape_comments": bool(query.get("scrape_comments", False))
		}

	def parse_tumblr_posts(self, posts):
		"""
		Function to parse Tumblr posts into the same dict items.
		Tumblr posts can be many different types, so some data processing is necessary.

		:param posts, list: List of Tumblr posts as returned form the Tumblr API.

		"""
		print(posts)
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

			# Different options for video types (YouTube- or Tumblr-hosted)
			if post_type == "video":
				if post["video_type"] == "youtube":
					# Use `get` since some videos are deleted
					video_url = post.get("permalink_url")
					# There's no URL if the post is deleted
					if video_url:
						video_id = post["video"]["youtube"]["video_id"]
					else:
						video_id = "deleted"
					video_source = "youtube"
				elif post["video_type"] == "tumblr":
					video_url = post["video_url"]
					video_id = None
					video_source = "tumblr"

			# All the fields to write
			processed_post = {
				"type": post_type,

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
				"date": post["date"],
				"timestamp": post["timestamp"],
				"body": text,
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
