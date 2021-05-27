"""
Search instagram via instaloader

Instagram is, after a fashion, an imageboard - people post images and then
other people reply (though they can't post images in response). So this
datasource uses this affordance to retrieve instagram data for 4CAT.
"""
import instaloader
import base64
import re

import config
from backend.abstract.search import Search
from common.lib.helpers import UserInput
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException


class SearchInstagram(Search):
	"""
	Instagram scraper
	"""
	type = "instagram-search"  # job ID
	category = "Search"  # category
	title = "Search Instagram"  # title displayed in UI
	description = "Retrieve Instagram posts by hashtag, user or location, in reverse chronological order."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	# not available as a processor for existing datasets
	accepts = [None]

	# let's not get rate limited
	max_workers = 1

	options = {
		"intro": {
			"type": UserInput.OPTION_INFO,
			"help": "Posts are scraped in reverse chronological order; the most recent post for a given query will be "
					"scraped first. In addition to posts, comments are also scraped. Note that this may take a long "
					"time for popular accounts or hashtags.\n\nYou can scrape up to **five** items at a time. Separate "
					"the items with commas or blank lines. Including `#` in hashtags is optional."
		},
		"search_scope": {
			"type": UserInput.OPTION_CHOICE,
			"help": "Search by",
			"options": {
				"hashtag": "Hashtag",
				"username": "Username"
			},
			"default": "hashtag"
		},
		"query": {
			"type": UserInput.OPTION_TEXT_LARGE,
			"help": "Items to scrape",
			"tooltip": "Separate with commas or new lines."
		},
		"scrape_comments": {
			"type": UserInput.OPTION_TOGGLE,
			"help": "Scrape comments?"
		},
		"max_posts": {
			"type": UserInput.OPTION_TEXT,
			"min": 1,
			"max": 500,
			"help": "Posts per item"
		}
	}

	def get_items(self, query):
		"""
		Run custom search

		Fetches data from Instagram via instaloader.
		"""
		# this is useful to include in the results because researchers are
		# always thirsty for them hashtags
		hashtag = re.compile(r"#([^\s,.+=-]+)")
		mention = re.compile(r"@([a-zA-Z0-9_]+)")

		instagram = instaloader.Instaloader(
			quiet=True,
			download_pictures=False,
			download_videos=False,
			download_comments=True,
			download_geotags=False,
			download_video_thumbnails=False,
			compress_json=False,
			save_metadata=True
		)

		# ready our parameters
		parameters = self.dataset.get_parameters()
		scope = parameters.get("search_scope", "")
		queries = [query.strip() for query in parameters.get("query", "").split(",")]

		posts = []
		max_posts = self.dataset.parameters.get("items", 500)

		# for each query, get items
		for query in queries:
			chunk_size = 0
			self.dataset.update_status("Retrieving posts ('%s')" % query)
			try:
				if scope == "hashtag":
					query = query.replace("#", "")
					chunk = instagram.get_hashtag_posts(query)
				elif scope == "username":
					query = query.replace("@", "")
					profile = instaloader.Profile.from_username(instagram.context, query)
					chunk = profile.get_posts()
				else:
					self.log.warning("Invalid search scope for instagram scraper: %s" % repr(scope))
					return []

				# "chunk" is a generator so actually retrieve the posts next
				posts_processed = 0
				for post in chunk:
					if self.interrupted:
						raise ProcessorInterruptedException("Interrupted while fetching posts from Instagram")

					chunk_size += 1
					self.dataset.update_status("Retrieving posts ('%s', %i posts)" % (query, chunk_size))
					if posts_processed >= max_posts:
						break
					try:
						posts.append(chunk.__next__())
						posts_processed += 1
					except StopIteration:
						break
			except instaloader.InstaloaderException as e:
				# should we abort here and return 0 posts?
				self.log.warning("Instaloader exception during query %s: %s" % (self.dataset.key, e))
				self.dataset.update_status("Error while retrieving posts for query '%s'" % query)

		# go through posts, and retrieve comments
		results = []
		posts_processed = 0
		comments_bit = " and comments" if self.parameters.get("scrape_comments", False) else ""

		for post in posts:
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while fetching post metadata from Instagram")

			posts_processed += 1
			self.dataset.update_status("Retrieving metadata%s for post %i" % (comments_bit, posts_processed))

			thread_id = post.shortcode

			try:
				results.append({
					"id": thread_id,
					"thread_id": thread_id,
					"parent_id": thread_id,
					"body": post.caption if post.caption is not None else "",
					"author": post.owner_username,
					"timestamp": int(post.date_utc.timestamp()),
					"type": "video" if post.is_video else "picture",
					"url": post.video_url if post.is_video else post.url,
					"thumbnail_url": post.url,
					"hashtags": ",".join(post.caption_hashtags),
					"usertags": ",".join(post.tagged_users),
					"mentioned": ",".join(mention.findall(post.caption) if post.caption else ""),
					"num_likes": post.likes,
					"num_comments": post.comments,
					"subject": ""
				})
			except (instaloader.QueryReturnedNotFoundException, instaloader.ConnectionException):
				pass

			if not self.parameters.get("scrape_comments", False):
				continue

			try:
				for comment in post.get_comments():
					answers = [answer for answer in comment.answers]

					try:
						results.append({
							"id": comment.id,
							"thread_id": thread_id,
							"parent_id": thread_id,
							"body": comment.text,
							"author": comment.owner.username,
							"timestamp": int(comment.created_at_utc.timestamp()),
							"type": "comment",
							"url": "",
							"hashtags": ",".join(hashtag.findall(comment.text)),
							"usertags": "",
							"mentioned": ",".join(mention.findall(comment.text)),
							"num_likes": comment.likes_count if hasattr(comment, "likes_count") else 0,
							"num_comments": len(answers),
							"subject": ""
						})
					except instaloader.QueryReturnedNotFoundException:
						pass

					# instagram only has one reply depth level at the time of
					# writing, represented here
					for answer in answers:
						try:
							results.append({
								"id": answer.id,
								"thread_id": thread_id,
								"parent_id": comment.id,
								"body": answer.text,
								"author": answer.owner.username,
								"timestamp": int(answer.created_at_utc.timestamp()),
								"type": "comment",
								"url": "",
								"hashtags": ",".join(hashtag.findall(answer.text)),
								"usertags": "",
								"mentioned": ",".join(mention.findall(answer.text)),
								"num_likes": answer.likes_count if hasattr(answer, "likes_count") else 0,
								"num_comments": 0,
								"subject": ""
							})
						except instaloader.QueryReturnedNotFoundException:
							pass

			except (instaloader.QueryReturnedNotFoundException, instaloader.ConnectionException):
				# data not available...? this happens sometimes, not clear why
				pass

		# remove temporary fetched data and return posts
		return results

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
		# no query 4 u
		if not query.get("query", "").strip():
			raise QueryParametersException("You must provide a search query.")

		# reformat queries to be a comma-separated list with no wrapping
		# whitespace
		whitespace = re.compile(r"\s+")
		items = whitespace.sub("", query.get("query").replace("\n", ","))
		if len(items.split(",")) > 5:
			raise QueryParametersException("You cannot query more than 5 items at a time.")

		# simple!
		return {
			"items": query.get("max_posts"),
			"query": items,
			"board": query.get("search_scope") + "s",  # used in web interface
			"search_scope": query.get("search_scope"),
			"scrape_comments": query.get("scrape_comments")
		}

	@staticmethod
	def salt_to_fernet_key():
		"""
		Use 4CAT's anonymisation salt to generate a Fernet encryption key

		THIS IS NOT A ROBUST ENCRYPTION METHOD. The goal here is to make it
		impossible to decrypt data if you have access to the database but
		*not* to the filesystem. If you have access to the 4CAT configuration
		file, it is trivial to generate this key yourself.

		For now however, it is better than storing the login details in the
		database in plain text.

		:return bytes:  Fernet-compatible 256-bit encryption key
		"""
		salt = config.ANONYMISATION_SALT
		while len(salt) < 32:
			salt += salt

		salt = bytearray(salt.encode("utf-8"))[0:32]
		return base64.urlsafe_b64encode(bytes(salt))
