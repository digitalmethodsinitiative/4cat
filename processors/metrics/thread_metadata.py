"""
Thread data
"""
import datetime
import math
import time

from backend.lib.processor import BasicProcessor

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

class ThreadMetadata(BasicProcessor):
	"""
	Extracts metadata on threads from the dataset.
	"""
	type = "thread-metadata"  # job type ID
	category = "Post metrics"  # category
	title = "Thread metadata"  # title displayed in UI
	description = "Extract various metadata on the threads in the dataset, including time data and post counts. Note " \
				  "that this extracted only on the basis of the items present this dataset."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with unique thread IDs and another one with the number
		of posts in that thread.
		"""
		threads = {}

		self.dataset.update_status("Reading source file")
		for post in self.source_dataset.iterate_items(self):
			if post["thread_id"] not in threads:
				threads[post["thread_id"]] = {
					"subject": post.get("subject", ""),
					"first_post": int(time.time()),
					"image_md5": "",  # only relevant for the chans
					"country_name": "",  # only relevant for the chans
					"op_body": "",
					"author": "",
					"last_post": 0,
					"images": 0,
					"count": 0,
				}

			if post.get("subject"):
				threads[post["thread_id"]]["subject"] = post.get("subject", "")

			if post.get("image_md5"):
				threads[post["thread_id"]]["images"] += 1

			if post["id"] == post["thread_id"]:
				threads[post["thread_id"]]["author"] = post.get("author", "")
				threads[post["thread_id"]]["country_name"] = post.get("country_name", "N/A")
				threads[post["thread_id"]]["image_md5"] = post.get("image_md5", "N/A")
				threads[post["thread_id"]]["op_body"] = post.get("body", "")

			timestamp = int(datetime.datetime.strptime(post["timestamp"], "%Y-%m-%d %H:%M:%S").timestamp())

			threads[post["thread_id"]]["first_post"] = min(timestamp, threads[post["thread_id"]]["first_post"])
			threads[post["thread_id"]]["last_post"] = max(timestamp, threads[post["thread_id"]]["last_post"])
			threads[post["thread_id"]]["count"] += 1

		results = [{
			"thread_id": thread_id,
			"timestamp": datetime.datetime.utcfromtimestamp(threads[thread_id]["first_post"]).strftime(
				'%Y-%m-%d %H:%M:%S'),
			"timestamp_lastpost": datetime.datetime.utcfromtimestamp(threads[thread_id]["last_post"]).strftime(
				'%Y-%m-%d %H:%M:%S'),
			"timestamp_unix": threads[thread_id]["first_post"],
			"timestamp_lastpost_unix": threads[thread_id]["last_post"],
			"subject": threads[thread_id]["subject"],
			"author": threads[thread_id]["author"],
			"op_body": threads[thread_id]["op_body"],
			"num_posts": threads[thread_id]["count"],
			"thread_age": (threads[thread_id]["last_post"] - threads[thread_id]["first_post"]),
			"thread_age_friendly": self.timify(threads[thread_id]["last_post"] - threads[thread_id]["first_post"]),
			**(
				{
					"num_images": threads[thread_id]["images"],
					"image_md5": threads[thread_id]["image_md5"],
					"country_code": threads[thread_id]["country_code"],
				} if self.source_dataset.type in ("fourchan", "eightchan", "eightkun") else {}
			)
		} for thread_id in threads]

		if not results:
			return

		self.write_csv_items_and_finish(results)

	def timify(self, number):
		"""
		For the non-geniuses, convert an amount of seconds to a more readable
		approximation like '4h 5m'

		:param int number:  Amount of seconds
		:return str:  Readable approximation
		"""
		try:
			number = int(number)
		except TypeError:
			return number

		time_str = ""

		hours = math.floor(number / 3600)
		if hours > 0:
			time_str += "%ih " % hours
			number -= (hours * 3600)

		minutes = math.floor(number / 60)
		if minutes > 0:
			time_str += "%im " % minutes
			number -= (minutes * 60)

		seconds = number
		time_str += "%is " % seconds

		return time_str.strip()
