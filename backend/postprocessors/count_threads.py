"""
Example post-processor worker
"""
from csv import DictReader, DictWriter

from backend.lib.postprocessor import BasicPostProcessor


class ThreadCounter(BasicPostProcessor):
	"""
	Example post-processor

	This is a very simple example post-processor.

	The four configuration options should be set for all post-processors. They
	contain information needed internally as well as information that is used
	to describe this post-processor with in a user interface.
	"""
	type = "thread-counter"  # job type ID
	title = "Thread and post counts"  # title displayed in UI
	description = "See how many threads and, for each thread, how many posts are present in the dataset"  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with unique thread IDs and another one with the number
		of posts in that thread.
		"""
		threads = {}

		self.query.update_status("Reading source file")
		with open(self.source_file) as source:
			csv = DictReader(source)
			for post in csv:
				if post["thread_id"] not in threads:
					threads[post["thread_id"]] = {
						"subject": post["subject"],
						"count": 0
					}

					if post["subject"]:
						threads[post["thread_id"]]["subject"] = post["subject"]

					threads[post["thread_id"]]["count"] += 1

		results = [{
			"thread_id": thread_id,
			"subject": threads[thread_id]["subject"],
			"num_posts": threads[thread_id]["count"]
		} for thread_id in threads]

		if not results:
			return

		self.query.write_csv_and_finish(results)