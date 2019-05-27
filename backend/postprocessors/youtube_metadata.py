"""
Thread data
"""
import datetime
import time

from csv import DictReader

from backend.abstract.postprocessor import BasicPostProcessor

import config


class YouTubeMetadata(BasicPostProcessor):
	"""
	
	Extracts data from YouTube URLs
	Every row is one link, with the metadata and `amount`
	of times shared.

	"""

	type = "youtube-metadata"  # job type ID
	category = "Post metrics" # category
	title = "YouTube metadata"  # title displayed in UI
	description = "Extract information from the YouTube links shared in your dataset."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with unique thread IDs and another one with the number
		of posts in that thread.
		"""
		threads = {}

		self.query.update_status("Reading source file")
		with open(self.source_file, encoding="utf-8") as source:
			csv = DictReader(source)
			for post in csv:
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
			"timestamp": datetime.datetime.fromtimestamp(threads[thread_id]["first_post"]).strftime('%Y-%m-%d %H:%M:%S'),
			"timestamp_lastpost": datetime.datetime.fromtimestamp(threads[thread_id]["last_post"]).strftime('%Y-%m-%d %H:%M:%S'),
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

		self.query.write_csv_and_finish(results)
