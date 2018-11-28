"""
Example post-processor worker
"""
from csv import DictReader, DictWriter

from backend.lib.postprocessor import BasicPostProcessor


class ThreadCounter(BasicPostProcessor):
	"""
	Example post-processor

	This is a very simple example post-processor.
	"""
	type = "thread-counter"

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
					threads[post["thread_id"]] = 0
				threads[post["thread_id"]] += 1

		self.query.update_status("Writing statistics to CSV file")
		results_path = self.query.get_results_path()
		with open(results_path, "w") as results:
			writer = DictWriter(results, fieldnames=("thread_id", "num_posts"))
			writer.writeheader()

			for thread_id in threads:
				writer.writerow({"thread_id": thread_id, "num_posts": threads[thread_id]})
