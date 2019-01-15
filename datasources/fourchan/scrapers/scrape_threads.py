"""
Thread scraper

Parses 4chan API data, saving it to database and queueing downloads
"""
import psycopg2
import hashlib
import os.path
import base64
import json
import six
import sys
import re

from backend.lib.helpers import get_absolute_folder
from backend.abstract.scraper import BasicJSONScraper
from backend.lib.exceptions import JobAlreadyExistsException

import config


class ThreadScraper4chan(BasicJSONScraper):
	"""
	Scrape 4chan threads

	This scrapes individual threads, and saves the posts into the database.

	Contains some provisions for 8chan's idiosyncracies as well, since that requires
	only a few lines of extra code and eliminates replicating the full class in the
	8chan scraper.
	"""
	type = "4chan-thread"
	max_workers = 1

	# for new posts, any fields not in here will be saved in the "unsorted_data" column for that post as part of a
	# JSONified dict
	known_fields = ["no", "resto", "sticky", "closed", "archived", "archived_on", "now", "time", "name", "trip", "id",
					"capcode", "country", "country_name", "sub", "com", "tim", "filename", "ext", "fsize", "md5", "w",
					"h", "tn_w", "tn_h", "filedeleted", "spoiler", "custom_spoiler", "omitted_posts", "omitted_images",
					"replies", "images", "bumplimit", "imagelimit", "capcode_replies", "last_modified", "tag",
					"semantic_url", "since4pass", "unique_ips", "tail_size"]

	# these fields should be present for every single post, and if they're not something weird is going on
	required_fields = ["no", "resto", "now", "time"]
	required_fields_op = ["no", "resto", "now", "time", "replies", "images"]

	def process(self, data):
		"""
		Process scraped thread data

		Adds new posts to the database, updates thread info, and queues images
		for downloading.

		:param dict data: The thread data, as parsed JSON data
		:return: The amount of posts added, or False if processing could not be completed
		"""
		self.platform = self.type.split("-")[0]

		if "posts" not in data or not data["posts"]:
			self.log.warning(
				"JSON response for thread %s/%s contained no posts, could not process" % (self.platform, self.job.data["remote_id"]))
			return False

		# check if OP has all the required data
		first_post = data["posts"][0]
		missing = set(self.required_fields_op) - set(first_post.keys())
		if missing != set():
			self.log.warning("OP is missing required fields %s, ignoring" % repr(missing))
			return False

		thread = self.update_thread(first_post,
									last_reply=max([post["time"] for post in data["posts"] if "time" in post]),
									last_post=max([post["no"] for post in data["posts"] if "no" in post]))

		if not thread:
			self.log.info("Thread %s/%s scraped, but no changes found" % (self.job.details["board"], first_post["no"]))
			return True

		thread_db_id = str(first_post["id"] if "id" in first_post and self.type != "4chan-thread" else first_post["no"])
		if thread["timestamp_deleted"] > 0:
			self.log.warning("Thread %s/%s/%s seems to have been undeleted, removing deletion timestamp %s" % (
			self.platform, self.job.details["board"], first_post["no"], thread["timestamp_deleted"]))
			self.db.update("threads_" + self.prefix, where={"id": thread_db_id}, data={"timestamp_deleted": 0})

		# create a dict mapped as `post id`: `post data` for easier comparisons with existing data
		post_dict_scrape = {str(post["no"]): post for post in data["posts"] if "no" in post}
		post_dict_db = {str(post["id"]): post for post in
						self.db.fetchall("SELECT * FROM posts_" + self.prefix + " WHERE thread_id = %s AND timestamp_deleted = 0 ORDER BY id ASC",
										 (thread_db_id,))}

		# mark deleted posts as such
		deleted = set(post_dict_db.keys()) - set(post_dict_scrape.keys())
		for post_id in deleted:
			self.db.update("posts_" + self.prefix, where={"id": post_id}, data={"timestamp_deleted": self.loop_time}, commit=False)
		self.db.commit()

		# add new posts
		new = set(post_dict_scrape.keys()) - set(post_dict_db.keys())
		new_posts = 0
		for post_id in new:
			added = self.save_post(post_dict_scrape[post_id], thread)
			if added:
				new_posts += 1

		# save to database
		self.log.info("Updating %s/%s/%s, new: %s, old: %s, deleted: %s" % (
			self.platform, self.job.details["board"], first_post["no"], new_posts, len(post_dict_db), len(deleted)))
		self.db.commit()

		return new_posts

	def save_post(self, post, thread):
		"""
		Add post to database

		:param dict post: Post data to add
		:param dict thread: Data for thread the post belongs to
		:return bool:  Whether the post was inserted
		"""
		# check for data integrity
		missing = set(self.required_fields) - set(post.keys())
		if missing != set():
			self.log.warning("Missing fields %s in scraped post, ignoring" % repr(missing))
			return False

		# save dimensions as a dumpable dict - no need to make it indexable
		if len({"w", "h", "tn_h", "tn_w"} - set(post.keys())) == 0:
			dimensions = {"w": post["w"], "h": post["h"], "tw": post["tn_w"], "th": post["tn_h"]}
		else:
			dimensions = {}

		post_data = {
			"id": post["no"],
			"thread_id": thread["id"],
			"timestamp": post["time"],
			"subject": post["sub"] if "sub" in post else "",
			"body": post["com"] if "com" in post else "",
			"author": post["name"] if "name" in post else "",
			"author_trip": post["trip"] if "trip" in post else "",
			"author_type": post["id"] if "id" in post and self.type == "4chan-thread" else "",
			"author_type_id": post["capcode"] if "capcode" in post else "",
			"country_code": post["country"] if "country" in post else "",
			"country_name": post["country_name"] if "country_name" in post else "",
			"image_file": post["filename"] + post["ext"] if "filename" in post else "",
			"image_4chan": str(post["tim"]) + post["ext"] if "filename" in post else "",
			"image_md5": post["md5"] if "md5" in post else "",
			"image_filesize": post["fsize"] if "fsize" in post else 0,
			"image_dimensions": json.dumps(dimensions),
			"semantic_url": post["semantic_url"] if "semantic_url" in post else "",
			"unsorted_data": json.dumps(
				{field: post[field] for field in post.keys() if field not in self.known_fields})
		}

		try:
			for field in post_data:
				if not isinstance(post_data[field], six.string_types):
					continue
				# apparently, sometimes \0 appears in posts or something; psycopg2 can't cope with this
				post_data[field] = post_data[field].replace("\0", "")

			self.db.insert("posts_" + self.prefix, post_data)
		except psycopg2.IntegrityError:
			self.db.rollback()
			dupe = self.db.fetchone("SELECT * from posts_" + self.prefix + " WHERE id = '%s'" % (str(post["no"]),), commit=False)
			if dupe:
				self.log.error("Post %s in thread %s/%s/%s (time: %s) scraped twice: first seen as %s in thread %s at %s" % (
				post["no"], self.platform, thread["board"], thread["id"], post["time"], dupe["id"], dupe["thread_id"], dupe["timestamp"]))
			else:
				self.log.error("Post %s in thread %s/%s/%s hit database constraint but no dupe was found?" % (
				post["no"], self.platform, thread["board"], thread["id"]))

			return False
		except ValueError as e:
			self.db.rollback()
			self.log.error("ValueError (%s) during scrape of thread %s" % (e, post["no"]))

		self.save_links(post, post["no"])
		if "filename" in post:
			self.queue_image(post, thread)

		return True

	def save_links(self, post, post_id):
		"""
		Save links to other posts in the given post

		Links are wrapped in a link with the "quotelink" class; the link is
		saved as a simple Post ID => Linked ID mapping.

		:param dict post:  Post data
		:param int post_id:  ID of the given post
		"""
		if "com" in post:
			links = re.findall('<a href="#p([0-9]+)" class="quotelink">', post["com"])
			for linked_post in links:
				if len(str(linked_post)) < 15:
					self.db.insert("posts_mention_" + self.prefix, {"post_id": post_id, "mentioned_id": linked_post}, safe=True,
								   commit=False)

	def queue_image(self, post, thread):
		"""
		Queue image for downloading

		This queues the image for downloading, if it hasn't been downloaded yet
		and a valid image folder has been set. This is the only place in the
		backend where the image path is determined!

		:param dict post:  Post data to queue image download for
		:param dict thread:  Thread data of thread within which image was posted
		"""

		# generate image path
		md5 = hashlib.md5()
		md5.update(base64.b64decode(post["md5"]))

		image_folder = get_absolute_folder(config.PATH_IMAGES)
		image_path = image_folder + "/" + md5.hexdigest() + post["ext"]

		if os.path.isdir(image_folder) and not os.path.isfile(image_path):
			try:
				self.queue.add_job("4chan-image", remote_id=post["md5"], details={
					"board": thread["board"],
					"ext": post["ext"],
					"tim": post["tim"],
					"destination": image_path
				})
			except JobAlreadyExistsException:
				pass

	def update_thread(self, first_post, last_reply, last_post):
		"""
		Update thread info

		Processes post data for the OP to see if the thread for that OP needs
		updating.

		:param dict first_post:  Post data for the OP
		:param int last_reply:  Timestamp of last reply in thread
		:param int last_post:  ID of last post in thread
		:return: Thread data (dict), updated, or `None` if no further work is needed
		"""
		# we need the following to check whether the thread has changed since the last scrape
		# 8chan doesn't always include this, in which case "-1" is as good a placeholder as any
		num_replies = first_post["replies"] + 1 if "replies" in first_post else -1

		# account for 8chan-style cyclical ID
		thread_db_id = str(first_post["id"] if "id" in first_post and self.type != "4chan-thread" else first_post["no"])

		thread = self.db.fetchone("SELECT * FROM threads_" + self.prefix + " WHERE id = %s", (thread_db_id,))
		if not thread:
			# self.log.warning("Tried to scrape post before thread %s was scraped" % first_post["no"])
			thread = self.add_thread(first_post, last_reply, last_post)

		if thread["num_replies"] == num_replies and num_replies != -1 and thread["timestamp_modified"] == last_reply:
			# no updates, no need to check posts any further
			self.log.debug("No new messages in thread %s" % first_post["no"])
			return None

		# first post has useful metadata for the *thread*

		# 8chan uses "bumplocked" but otherwise it's the same
		bumplimit = ("bumplimit" in first_post and first_post["bumplimit"] == 1) or (
					"bumplocked" in first_post and first_post["bumplocked"] == 1)

		# compile data
		thread_update = {
			"timestamp": first_post["time"],
			"num_unique_ips": first_post["unique_ips"] if "unique_ips" in first_post else -1,
			"num_images": first_post["images"] if "images" in first_post else -1,
			"num_replies": num_replies,
			"limit_bump": bumplimit,
			"limit_image": ("imagelimit" in first_post and first_post["imagelimit"] == 1),
			"is_sticky": ("sticky" in first_post and first_post["sticky"] == 1),
			"is_closed": ("closed" in first_post and first_post["closed"] == 1),
			"post_last": last_post
		}

		if "archived" in first_post and first_post["archived"] == 1:
			thread_update["timestamp_archived"] = first_post["archived_on"]

		self.db.update("threads_" + self.prefix, where={"id": thread_db_id}, data=thread_update)
		return {**thread, **thread_update}

	def add_thread(self, first_post, last_reply, last_post):
		"""
		Add thread to database

		This should not happen, usually. But if a thread is not in the database yet when it is scraped, add some basic
		data and let the update method handle the rest of the details.

		:param dict first_post:  Post data for the OP
		:param int last_reply:  Timestamp of last reply in thread
		:param int last_post:  ID of last post in thread
		:return dict:  Thread row that was added
		"""

		# account for 8chan-style cyclical threads
		thread_db_id = str(first_post["id"] if "id" in first_post and self.type != "4chan-thread" else first_post["no"])

		self.db.insert("threads_" + self.prefix, {
			"id": thread_db_id,
			"board": self.job.details["board"],
			"timestamp": first_post["time"],
			"timestamp_scraped": self.loop_time,
			"timestamp_modified": first_post["time"],
			"post_last": last_post
		})

		return self.db.fetchone("SELECT * FROM threads_" + self.prefix + " WHERE id = %s", (thread_db_id,))

	def not_found(self):
		"""
		If the resource could not be found, that indicates the whole thread has
		been deleted.
		"""
		self.platform = self.type.split("-")[0]
		thread_db_id = self.job.data["remote_id"].split("/").pop()
		self.log.info(
			"Thread %s/%s/%s was deleted, marking as such" % (self.platform, self.job.details["board"], self.job.data["remote_id"]))
		self.db.update("threads_" + self.prefix, data={"timestamp_deleted": self.loop_time},
					   where={"id": thread_db_id, "timestamp_deleted": 0})
		self.job.finish()

	def get_url(self):
		"""
		Get URL to scrape for the current job

		:return string: URL to scrape
		"""
		thread_id = self.job.data["remote_id"].split("/").pop()
		return "http://a.4cdn.org/%s/thread/%s.json" % (self.job.details["board"], thread_id)
