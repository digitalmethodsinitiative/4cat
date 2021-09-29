"""
Thread scraper

Parses 4chan API data, saving it to database and queueing downloads

Flow:

(crawler)
-> process():
   -> register_thread(): check if thread exists
      if not, create preliminary record
      -> add_thread()
      if so,
        if no change in timestamp or number of posts, DONE (halt processing)
        if changes, continue
   -> create separate sets of new posts and deleted posts
   -> mark deleted posts as deleted
   -> add new posts to database
      -> save_post(): save post data to database
         -> queue_image(): if an image was attached, queue a job to scrape it
   -> update_thread(): update thread data
"""
import requests
import psycopg2
import hashlib
import base64
import flag
import json
import time
import six

from pathlib import Path

from backend.abstract.scraper import BasicJSONScraper
from common.lib.exceptions import JobAlreadyExistsException
from common.lib.helpers import strip_tags

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
	max_workers = 4

	# for new posts, any fields not in here will be saved in the "unsorted_data" column for that post as part of a
	# JSONified dict
	known_fields = ["no", "resto", "sticky", "closed", "archived", "archived_on", "now", "time", "name", "trip", "id",
					"capcode", "country", "country_name", "board_flag", "flag_name", "sub", "com", "tim", "filename", "ext", "fsize", "md5", "w",
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
		self.datasource = self.type.split("-")[0]

		if "posts" not in data or not data["posts"]:
			self.log.warning(
				"JSON response for thread %s/%s contained no posts, could not process" % (self.datasource, self.job.data["remote_id"]))
			return False

		# determine OP id (8chan sequential threads are an exception here)
		first_post = data["posts"][0]
		thread_db_id = str(first_post["id"] if "id" in first_post and self.type != "4chan-thread" else first_post["no"])

		# check if OP has all the required data
		missing = set(self.required_fields_op) - set(first_post.keys())
		if missing != set():
			self.log.warning("OP is missing required fields %s, ignoring" % repr(missing))
			return False

		# check if thread exists and has new data
		last_reply = max([post["time"] for post in data["posts"] if "time" in post])
		last_post = max([post["no"] for post in data["posts"] if "no" in post])
		thread = self.register_thread(first_post, last_reply, last_post, num_replies=len(data["posts"]))

		if not thread:
			self.log.info("Thread %s/%s/%s scraped, but no changes found" % (self.datasource, self.job.details["board"], first_post["no"]))
			return True

		if thread["timestamp_deleted"] > 0:
			self.log.info("Thread %s/%s/%s seems to have been undeleted, removing deletion timestamp %s" % (
			self.datasource, self.job.details["board"], first_post["no"], thread["timestamp_deleted"]))
			self.db.update("threads_" + self.prefix, where={"id": thread_db_id}, data={"timestamp_deleted": 0})

		# create a dict mapped as `post id`: `post data` for easier comparisons with existing data
		known_posts = self.db.fetchall("SELECT id, id_seq FROM posts_" + self.prefix + " WHERE thread_id = %s AND board = %s ORDER BY id ASC",
										 (thread_db_id, self.job.details["board"]))
		post_dict_scrape = {str(post["no"]): post for post in data["posts"] if "no" in post}
		post_dict_db = {str(post["id"]): post for post in known_posts}
		post_id_map = {str(post["id"]): post["id_seq"] for post in known_posts}

		# mark deleted posts as such
		deleted = set(post_dict_db.keys()) - set(post_dict_scrape.keys())
		for post_id in deleted:
			self.db.upsert("posts_%s_deleted" % self.prefix, data={"id_seq": post_id_map[post_id], "timestamp_deleted": self.init_time}, constraints=["id_seq"], commit=False)
		self.db.commit()

		# add new posts
		new = set(post_dict_scrape.keys()) - set(post_dict_db.keys())
		new_posts = 0
		new_ids = set()
		for post_id in new:
			added = self.save_post(post_dict_scrape[post_id], thread, first_post)
			if added:
				new_posts += 1
				new_ids.add(added)

		all_ids = set([post_id_map[post_id] for post_id in post_dict_scrape.keys() if post_id in post_id_map]).union(new_ids)
		undeleted = 0
		if all_ids:
			undeleted = self.db.delete("posts_%s_deleted" % self.prefix, where={"id_seq": list(all_ids)})

		# update thread data
		self.db.commit()
		self.update_thread(thread, first_post, last_reply, last_post, thread["num_replies"] + new_posts)

		# save to database
		self.log.info("Updating %s/%s/%s, new: %s, old: %s, deleted: %s, undeleted: %s" % (
			self.datasource, self.job.details["board"], first_post["no"], new_posts, len(post_dict_db), len(deleted), undeleted))
		self.db.commit()

		# return the amount of new posts
		return new_posts

	def save_post(self, post, thread, first_post):
		"""
		Add post to database

		:param dict post: Post data to add
		:param dict thread: Data for thread the post belongs to
		:param dict first_post:  First post in thread
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

		# aggregate post data
		post_data = {
			"id": post["no"],
			"board": self.job.details["board"],
			"thread_id": thread["id"],
			"timestamp": post["time"],
			"subject": post.get("sub", ""),
			"body": post.get("com", ""),
			"author": post.get("name", ""),
			"author_trip": post.get("trip", ""),
			"author_type": post["id"] if "id" in post and self.type == "4chan-thread" else "",
			"author_type_id": post.get("capcode", ""),
			"country_code": post.get("country", "") if "board_flag" not in post else "t_" + post["board_flag"],
			"country_name": post.get("country_name", "") if "flag_name" not in post else post["flag_name"],
			"image_file": post["filename"] + post["ext"] if "filename" in post else "",
			"image_4chan": str(post["tim"]) + post["ext"] if "filename" in post else "",
			"image_md5": post.get("md5", ""),
			"image_filesize": post.get("fsize", 0),
			"image_dimensions": json.dumps(dimensions),
			"semantic_url": post.get("semantic_url", ""),
			"unsorted_data": json.dumps(
				{field: post[field] for field in post.keys() if field not in self.known_fields})
		}

		# this is mostly unsupported, feel free to ignore
		if hasattr(config, "HIGHLIGHT_SLACKHOOK") and hasattr(config, "HIGHLIGHT_MATCH") and self.type == "4chan-thread":
			for highlight in config.HIGHLIGHT_MATCH:
				attachments = []
				if highlight.lower() in post_data["body"].lower():
					if not post_data["country_code"]:
						country_flag = " (%s)" % post_data["country_name"] if post_data["country_name"] else ""
					else:
						pattern = " :%s:" % post_data["country_code"]
						country_flag = flag.flagize(pattern)
						if country_flag == pattern:
							country_flag = " (%s)" % post_data["country_code"]
						else:
							print(repr(country_flag))

					subject = first_post.get("sub", first_post["no"])
					attachments.append({
						"title": "%s%s in '%s''" % (post_data["author"], country_flag, subject),
						"title_link": "https://boards.4chan.org/%s/thread/%s#pc%s" % (thread["board"], thread["id"], post_data["id"]),
						"text": strip_tags(post_data["body"], convert_newlines=True).replace(highlight, "*%s*" % highlight),
						"mrkdwn_in": ["text", "pretext"],
						"color": "#73ad34"
					})

				if not attachments:
					continue

				try:
					requests.post(config.HIGHLIGHT_SLACKHOOK, json.dumps({
						"text": "A post mentioning '%s' was just scraped from 4chan /%s/:" % (highlight, thread["board"]),
						"attachments": attachments
					}))
				except requests.RequestException as e:
					self.log.warning("Could not send highlight alerts to Slack webhook (%s)" % e)


		# now insert the post into the database
		return_value = True
		try:
			for field in post_data:
				if not isinstance(post_data[field], six.string_types):
					continue
				# apparently, sometimes \0 appears in posts or something; psycopg2 can't cope with this
				post_data[field] = post_data[field].replace("\0", "")

			return_value = self.db.insert("posts_" + self.prefix, post_data, return_field="id_seq")
		except psycopg2.IntegrityError as e:
			self.db.rollback()
			dupe = self.db.fetchone("SELECT * from posts_" + self.prefix + " WHERE id = %s" % (str(post["no"]),))
			if dupe:
				self.log.info("Post %s in thread %s/%s/%s (time: %s) scraped twice: first seen as %s in thread %s at %s" % (
				 post["no"], self.datasource, thread["board"], thread["id"], post["time"], dupe["id"], dupe["thread_id"], dupe["timestamp"]))
			else:
				self.log.error("Post %s in thread %s/%s/%s hit database constraint (%s) but no dupe was found?" % (
				post["no"], self.datasource, thread["board"], thread["id"], e))

			return False
		except ValueError as e:
			self.db.rollback()
			self.log.error("ValueError (%s) during scrape of thread %s" % (e, post["no"]))

		# Download images (exclude .webm files)
		if "filename" in post and post["ext"] != ".webm":
			self.queue_image(post, thread)

		return return_value

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

		image_folder = Path(config.PATH_ROOT, config.PATH_IMAGES)
		image_path = image_folder.joinpath(md5.hexdigest() + post["ext"])

		if config.PATH_IMAGES and image_folder.is_dir() and not image_path.is_file():
			claimtime = int(time.time()) + config.IMAGE_INTERVAL

			try:
				self.queue.add_job("4chan-image", remote_id=post["md5"], claim_after=claimtime, details={
					"board": thread["board"],
					"ext": post["ext"],
					"tim": post["tim"],
					"destination": str(image_path),
				})
			except JobAlreadyExistsException:
				pass

	def register_thread(self, first_post, last_reply, last_post, num_replies):
		"""
		Check if thread exists

		Acquires thread data from the database and determines whether there is
		any new data that belongs to this thread.

		:param dict first_post:  Post data for the OP
		:param int last_reply:  Timestamp of last reply in thread
		:param int last_post:  ID of last post in thread
		:param int num_replies:  Number of posts in thread (including OP)
		:return: Thread data (dict), updated, or `None` if no further work is needed
		"""
		# we need the following to check whether the thread has changed since the last scrape
		# 8chan doesn't always include this, in which case "-1" is as good a placeholder as any
		# account for 8chan-style cyclical ID
		thread_db_id = str(first_post["id"] if "id" in first_post and self.type != "4chan-thread" else first_post["no"])
		thread = self.db.fetchone("SELECT * FROM threads_" + self.prefix + " WHERE id = %s", (thread_db_id,))

		if not thread:
			# This very rarely happens, but sometimes the thread is not yet in the database, somehow
			# In this case, a thread with the bare minimum of metadata is created - more extensive
			# data will be added in update_thread later.
			thread = self.add_thread(first_post, last_reply, last_post)
			return thread

		if thread["num_replies"] == num_replies and num_replies != -1 and thread["timestamp_modified"] == last_reply:
			# no updates, no need to check posts any further
			self.log.debug("No new messages in thread %s" % first_post["no"])
			return None
		else:
			return thread

	def update_thread(self, thread, first_post, last_reply, last_post, num_replies):
		"""
		Update thread info

		:param dict first_post:  Post data for the OP
		:param int last_reply:  Timestamp of last reply in thread
		:param int last_post:  ID of last post in thread
		:param int num_replies:  Number of posts in thread (including OP)
		:return: Thread data (dict), updated, or `None` if no further work is needed
		"""
		thread_db_id = str(first_post["id"] if "id" in first_post and self.type != "4chan-thread" else first_post["no"])

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

		This should not happen, usually. But if a thread is not in the database
		yet when it is scraped, add some basic data and let the update method
		handle the rest of the details.

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
			"timestamp_scraped": self.init_time,
			"timestamp_modified": first_post["time"],
			"post_last": last_post
		})

		return self.db.fetchone("SELECT * FROM threads_" + self.prefix + " WHERE id = %s", (thread_db_id,))

	def not_found(self):
		"""
		If the resource could not be found, that indicates the whole thread has
		been deleted.
		"""
		self.datasource = self.type.split("-")[0]
		thread_db_id = self.job.data["remote_id"].split("/").pop()
		self.log.info(
			"Thread %s/%s/%s was deleted, marking as such" % (self.datasource, self.job.details["board"], self.job.data["remote_id"]))
		self.db.update("threads_" + self.prefix, data={"timestamp_deleted": self.init_time},
					   where={"id": thread_db_id, "timestamp_deleted": 0})
		self.job.finish()

	def get_url(self):
		"""
		Get URL to scrape for the current job

		:return string: URL to scrape
		"""
		thread_id = self.job.data["remote_id"].split("/").pop()
		return "http://a.4cdn.org/%s/thread/%s.json" % (self.job.details["board"], thread_id)
