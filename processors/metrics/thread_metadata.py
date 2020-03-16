"""
Thread data
"""
import datetime
import time

from csv import DictReader

from backend.abstract.processor import BasicProcessor

import config

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

class ThreadMetadata(BasicProcessor):
	"""
	Example post-processor

	This is a very simple example post-processor.

	The four configuration options should be set for all post-processors. They
	contain information needed internally as well as information that is used
	to describe this post-processor with in a user interface.
	"""
	type = "thread-metadata"  # job type ID
	category = "Thread metrics"  # category
	title = "Thread metadata"  # title displayed in UI
	description = "Create an overview of the threads present in the dataset, containing thread IDs, subjects and post counts."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI
	datasources = ["4chan", "8chan"]

	input = "csv:id,thread_id,subject,author,body"
	output = "csv:thread_id,timestamp,timestamp_lastpost,timestamp_unix,timestamp_lastpost_unix,subject,author,op_body,country_code,num_posts,num_images,image_md5,preview_url"

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with unique thread IDs and another one with the number
		of posts in that thread.
		"""
		threads = {}

		self.dataset.update_status("Reading source file")
		for post in self.iterate_csv_items(self.source_file):
			if post["thread_id"] not in threads:
				threads[post["thread_id"]] = {
					"subject": post["subject"],
					"first_post": int(time.time()),
					"image_md5": "",
					"country_code": "",
					"op_body": "",
					"author": "",
					"last_post": 0,
					"images": 0,
					"count": 0,
				}

			if post["subject"]:
				threads[post["thread_id"]]["subject"] = post["subject"]

			if post["image_md5"]:
				threads[post["thread_id"]]["images"] += 1

			if post["id"] == post["thread_id"]:
				threads[post["thread_id"]]["author"] = post["author"]
				threads[post["thread_id"]]["country_code"] = post["country_code"]
				threads[post["thread_id"]]["image_md5"] = post["image_md5"]
				threads[post["thread_id"]]["op_body"] = post["body"]

			timestamp = int(datetime.datetime.strptime(post["timestamp"], "%Y-%m-%d %H:%M:%S").timestamp())

			threads[post["thread_id"]]["first_post"] = min(timestamp, threads[post["thread_id"]]["first_post"])
			threads[post["thread_id"]]["last_post"] = max(timestamp, threads[post["thread_id"]]["last_post"])
			threads[post["thread_id"]]["count"] += 1

		results = [{
			"thread_id": thread_id,
			"timestamp": datetime.datetime.fromtimestamp(threads[thread_id]["first_post"]).strftime(
				'%Y-%m-%d %H:%M:%S'),
			"timestamp_lastpost": datetime.datetime.fromtimestamp(threads[thread_id]["last_post"]).strftime(
				'%Y-%m-%d %H:%M:%S'),
			"timestamp_unix": threads[thread_id]["first_post"],
			"timestamp_lastpost_unix": threads[thread_id]["last_post"],
			"subject": threads[thread_id]["subject"],
			"author": threads[thread_id]["author"],
			"op_body": threads[thread_id]["op_body"],
			"country_code": threads[thread_id]["country_code"],
			"num_posts": threads[thread_id]["count"],
			"num_images": threads[thread_id]["images"],
			"image_md5": threads[thread_id]["image_md5"],
			"preview_url": "http://" + config.FlaskConfig.SERVER_NAME + "/api/4chan/pol/thread/" + str(
				thread_id) + ".json?format=html"
		} for thread_id in threads]

		if not results:
			return

		self.write_csv_items_and_finish(results)
