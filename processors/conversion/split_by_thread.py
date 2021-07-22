"""
Split results by thread
"""
import zipfile
import shutil
import csv

from backend.abstract.processor import BasicProcessor

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)

class ThreadSplitter(BasicProcessor):
	"""
	Create separate result files per thread

	Take a results file, and create separate result files per thread, each
	containing only the posts in that thread.
	"""
	type = "split-threads"  # job type ID
	category = "Conversion" # category
	title = "Split by thread"  # title displayed in UI
	description = "Split the result over separate csv files per thread. The threads can then be downloaded as an archive containing the separate CSV files."  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Determine if processor is compatible with dataset

		:param module: Dataset or processor to determine compatibility with
		"""
		if module.is_dataset():
			return module.parameters.get("datasource") in ("4chan", "8chan", "reddit", "breitbart")
		return False
		
	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with unique usernames and in the other one the amount
		of posts for that user name
		"""
		users = {}

		# prepare staging area
		results_path = self.dataset.get_staging_area()

		# read and write
		self.dataset.update_status("Creating thread files")
		for post in self.iterate_items(self.source_file):
			thread = results_path.joinpath(post["thread_id"] + ".csv")
			new = not thread.exists()

			with thread.open("a", encoding="utf-8") as output:
				outputcsv = csv.DictWriter(output, fieldnames=post.keys())

				if new:
					outputcsv.writeheader()

				outputcsv.writerow(post)

		self.write_archive_and_finish(results_path)