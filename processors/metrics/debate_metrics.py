"""
Get regular and 'debate' thread metadata
"""
import datetime
import time

from backend.abstract.processor import BasicProcessor

import config

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

class DebateMetrics(BasicProcessor):
	"""
	Create a csv with debate metrics per thread, in addition
	to those in the `thread_metadata` processor.

	op_length: length of op post (with URLs)
	op_replies: replies to the OP 
	reply_amount: posts (other than the OP) that have been replied to
	active_users: unique users with ≥ 1 posts
	reply_length: average length of a reply (without URLs)
	long_messages: 'long messages', i.e. more than 100 characters

	"""
	type = "debate_metrics"  # job type ID
	category = "Thread metrics" # category
	title = "Debate metrics"  # title displayed in UI
	description = "Returns a csv with meta-metrics per thread."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor if dataset is a 'top level' dataset

		:param module: Dataset or processor to determine compatibility with
		"""
		if module.is_dataset():
			return module.parameters.get("datasource") in ("4chan", "8chan", "8kun")
		return False

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a csv
		with a thread per row with its debate metrics.
		"""

		threads = {}
		reply_lengths = []
		
		datasource = self.source_dataset.parameters["datasource"]
		board = self.source_dataset.parameters["board"]

		self.dataset.update_status("Reading source file")
		for post in self.iterate_items(self.source_file):
			if post["thread_id"] not in threads:
				threads[post["thread_id"]] = {
					"subject": post["subject"],
					"first_post": int(time.time()),
					"images": 0,
					"count": 0,
					"op_length": len(post["body"])
				}

			if post["subject"]:
				threads[post["thread_id"]]["subject"] = post["subject"]

			if post["image_md5"]:
				threads[post["thread_id"]]["images"] += 1

			timestamp = int(datetime.datetime.strptime(post["timestamp"], "%Y-%m-%d %H:%M:%S").timestamp())

			threads[post["thread_id"]]["first_post"] = min(timestamp, threads[post["thread_id"]]["first_post"])
			threads[post["thread_id"]]["count"] += 1

		results = [{
			"thread_id": thread_id,
			"timestamp": datetime.datetime.utcfromtimestamp(threads[thread_id]["first_post"]).strftime('%Y-%m-%d %H:%M:%S'),
			"subject": threads[thread_id]["subject"],
			"num_posts": threads[thread_id]["count"],
			"num_images": threads[thread_id]["images"],
			"preview_url": "http://" + config.FlaskConfig.SERVER_NAME + "/api/" + datasource + "/" + board + "/thread/" + str(
				thread_id) + ".json?format=html",
			"op_replies": threads[thread_id]["op_length"]
			# "reply_amount": ,
			# "active_users": ,
			# "reply_length": ,
			# "long_messages":
		} for thread_id in threads]

		if not results:
			return

		self.write_csv_items_and_finish(results)
