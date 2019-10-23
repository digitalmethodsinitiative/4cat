"""
Search instagram via instaloader

Instagram is, after a fashion, an imageboard - people post images and then
other people reply (though they can't post images in response). So this
datasource uses this affordance to retrieve instagram data for 4CAT.
"""
import instaloader
import shutil
import os
import re

from backend.abstract.search import Search
from backend.lib.exceptions import QueryParametersException


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
		self.job.finish()

		# this is useful to include in the results because researchers are
		# always thirsty for them hashtags
		hashtag = re.compile(r"#([^\s,.+=-]+)")
		mention = re.compile(r"@([a-zA-Z0-9_]+)")

		# this is mostly unused given our instaloader settings, but reserve a
		# folder for temporary downloaded data
		working_directory = self.dataset.get_temporary_path()
		working_directory.mkdir()
		os.chdir(working_directory)

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
					profile = instaloader.Profile.from_username(instagram.context, query)
					chunk = profile.get_posts()
				else:
					self.log.warning("Invalid search scope for instagram scraper: %s" % repr(scope))
					return []

				# "chunk" is a generator so actually retrieve the posts next
				posts_processed = 0
				for post in chunk:
					chunk_size += 1
					self.dataset.update_status("Retrieving posts ('%s', %i posts)" % (query, chunk_size))
					if posts_processed >= max_posts:
						break
					posts.append(chunk.__next__())
					posts_processed += 1
			except instaloader.InstaloaderException:
				# should we abort here and return 0 posts?
				self.log.info("Instaloader exception during query %s" % self.dataset.key)

		# go through posts, and retrieve comments
		results = []
		posts_processed = 0
		comments_bit = " and comments" if self.parameters.get("scrape_comments", False) else ""

		for post in posts:
			posts_processed += 1
			self.dataset.update_status("Retrieving metadata%s for post %i" % (comments_bit, posts_processed))

			thread_id = post.shortcode

			try:
				post_username = post.owner_username
			except instaloader.QueryReturnedNotFoundException:
				post_username = ""

			results.append({
				"id": thread_id,
				"thread_id": thread_id,
				"parent_id": thread_id,
				"body": post.caption if post.caption is not None else "",
				"author": post_username,
				"timestamp": int(post.date_utc.timestamp()),
				"type": "video" if post.is_video else "picture",
				"url": post.video_url if post.is_video else post.url,
				"hashtags": ",".join(post.caption_hashtags),
				"usertags": ",".join(post.tagged_users),
				"mentioned": ",".join(mention.findall(post.caption) if post.caption else ""),
				"num_likes": post.likes,
				"num_comments": post.comments,
				"subject": ""
			})

			if not self.parameters.get("scrape_comments", False):
				continue

			for comment in post.get_comments():
				answers = [answer for answer in comment.answers]

				try:
					comment_username = comment.owner_username
				except instaloader.QueryReturnedNotFoundException:
					comment_username = ""

				results.append({
					"id": comment.id,
					"thread_id": thread_id,
					"parent_id": thread_id,
					"body": comment.text,
					"author": comment_username,
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

				# instagram only has one reply depth level at the time of
				# writing, represented here
				for answer in answers:
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

		# remove temporary fetched data and return posts
		shutil.rmtree(working_directory)
		return results

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
		if query.get("search_scope", "") not in ("hashtag", "username"):
			raise QueryParametersException("Invalid search scope: must be hashtag or username")

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

		# reformat queries to be a comma-separated list with no wrapping
		# whitespace
		whitespace = re.compile(r"\s+")
		items = whitespace.sub("", query.get("query").replace("\n", ","))
		if len(items.split(",")) > 5:
			raise QueryParametersException("You cannot query more than 5 items at a time.")

		# simple!
		return {
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
