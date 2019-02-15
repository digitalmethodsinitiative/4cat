"""
Thread data
"""
import datetime
import time

from csv import DictReader

from backend.abstract.postprocessor import BasicPostProcessor

import config


class ThreadCounter(BasicPostProcessor):
	"""
	Example post-processor

	This is a very simple example post-processor.

	The four configuration options should be set for all post-processors. They
	contain information needed internally as well as information that is used
	to describe this post-processor with in a user interface.
	"""
	type = "thread-counter"  # job type ID
	category = "Thread metrics" # category
	title = "Thread metadata"  # title displayed in UI
	description = "Create an overview of the threads present in the dataset, containing thread IDs, subjects and post counts."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with unique thread IDs and another one with the number
		of posts in that thread.
		"""
		threads = {}

		self.query.update_status("Reading source file")
		with open(self.source_file, encoding='utf-8') as source:
			csv = DictReader(source)
			for post in csv:
				if post["thread_id"] not in threads:
					threads[post["thread_id"]] = {
						"subject": post["subject"],
						"first_post": int(time.time()),
						"images": 0,
						"count": 0,
					}

				if post["subject"]:
					threads[post["thread_id"]]["subject"] = post["subject"]

				if post["image_md5"]:
					threads[post["thread_id"]]["images"] += 1

				timestamp = int(
					post.get("unix_timestamp", datetime.datetime.fromisoformat(post["timestamp"]).timestamp))
				threads[post["thread_id"]]["first_post"] = min(timestamp, threads[post["thread_id"]]["first_post"])
				threads[post["thread_id"]]["count"] += 1

		results = [{
			"thread_id": thread_id,
			"timestamp": datetime.datetime.utcfromtimestamp(threads[thread_id]["first_post"]).strftime(
				'%Y-%m-%d %H:%M:%S'),
			"subject": threads[thread_id]["subject"],
			"num_posts": threads[thread_id]["count"],
			"num_images": threads[thread_id]["images"],
			"preview_url": "http://" + config.FlaskConfig.SERVER_NAME + "/api/4chan/pol/thread/" + str(
				thread_id) + ".json?format=html"
		} for thread_id in threads]

		if not results:
			return

		self.query.write_csv_and_finish(results)
