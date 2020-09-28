"""
Search instagram via instaloader

Instagram is, after a fashion, an imageboard - people post images and then
other people reply (though they can't post images in response). So this
datasource uses this affordance to retrieve instagram data for 4CAT.
"""
import instaloader
import shutil
import base64
import json
import os
import re

from cryptography.fernet import Fernet

import config
from backend.abstract.search import Search
from backend.lib.exceptions import QueryParametersException, ProcessorInterruptedException


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

	def get_posts_simple(self, query):
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

		# log in, because else Instagram gets really annoying with rate
		# limits
		if config.DATASOURCES.get("instagram", {}).get("require_login", False):
			if not parameters.get("login", None):
				self.dataset.update_status(
					"No Instagram login provided. Create a new dataset and provide your login details to scrape.",
					is_final=True)
				return []
			key = SearchInstagram.salt_to_fernet_key()
			fernet = Fernet(key)
			login = json.loads(fernet.decrypt(parameters.get("login").encode("utf-8")))

			try:
				instagram.login(login[0], login[1])
			except instaloader.TwoFactorAuthRequiredException:
				self.dataset.update_status(
					"Two-factor authentication with Instagram is not available via 4CAT at this time. Disable it for your Instagram account and try again.",
					is_final=True)
				return []
			except (instaloader.InvalidArgumentException, instaloader.BadCredentialsException):
				self.dataset.update_status("Invalid Instagram username or password", is_final=True)
				return []
			except instaloader.ConnectionException:
				self.dataset.update_status("Could not connect to Instagram to log in.", is_final=True)
				return []

		# if we have the login in memory now, get rid of the login info stored
		# in the database
		self.dataset.delete_parameter("login")

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

		# 'location' would be possible as well but apparently requires a login
		if query.get("search_scope", "") not in ("hashtag", "username"):
			raise QueryParametersException("Invalid search scope: must be hashtag or username")

		# no query 4 u
		if not query.get("query", "").strip():
			raise QueryParametersException("You must provide a search query.")

		# test if login is valid, if that is needed
		if config.DATASOURCES.get("instagram", {}).get("require_login", False):
			if not query.get("username", "").strip() or not query.get("password", "").strip():
				raise QueryParametersException("You need to provide a username and password")

			username = query.get("username")
			password = query.get("password")
			login_tester = instaloader.Instaloader()
			try:
				login_tester.login(username, password)
			except instaloader.TwoFactorAuthRequiredException:
				raise QueryParametersException(
					"Two-factor authentication with Instagram is not available via 4CAT at this time. Disable it for your Instagram account and try again.")
			except (instaloader.InvalidArgumentException, instaloader.BadCredentialsException):
				raise QueryParametersException("Invalid Instagram username or password.")

			# there are some fundamental limits to how safe we can make this, but
			# we can at least encrypt it so that if someone has access to the
			# database but not the 4CAT config file, they cannot use the login
			# details
			# we use the 4CAT anyonymisation salt (which *should* be a long,
			# random string)
			# making sure the 4CAT config file is kept safe is left as an exercise
			# for the reader...
			key = SearchInstagram.salt_to_fernet_key()
			fernet = Fernet(key)
			obfuscated_login = fernet.encrypt(json.dumps([username, password]).encode("utf-8")).decode("utf-8")
		else:
			obfuscated_login = ""

		# 500 is mostly arbitrary - may need tweaking
		max_posts = 2500
		if query.get("max_posts", ""):
			try:
				max_posts = min(abs(int(query.get("max_posts"))), max_posts)
			except TypeError:
				raise QueryParametersException("Provide a valid number of posts to query.")

		# reformat queries to be a comma-separated list with no wrapping
		# whitespace
		whitespace = re.compile(r"\s+")
		items = whitespace.sub("", query.get("query").replace("\n", ","))
		if len(items.split(",")) > 5:
			raise QueryParametersException("You cannot query more than 5 items at a time.")

		# simple!
		return {
			"login": obfuscated_login,
			"items": max_posts,
			"query": items,
			"board": query.get("search_scope") + "s",  # used in web interface
			"search_scope": query.get("search_scope"),
			"scrape_comments": bool(query.get("scrape_comments", False))
		}

	def get_search_mode(self, query):
		"""
		Instagram searches are always simple

		:return str:
		"""
		return "simple"

	def get_posts_complex(self, query):
		"""
		Complex post fetching is not used by the Instagram datasource

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
		Thread filtering is not a toggle for Instagram datasets

		:param thread_ids:
		:return:
		"""
		pass

	def get_thread_sizes(self, thread_ids, min_length):
		"""
		Thread filtering is not a toggle for Instagram datasets

		:param tuple thread_ids:
		:param int min_length:
		results
		:return dict:
		"""
		pass

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
