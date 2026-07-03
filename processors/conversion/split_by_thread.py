"""
Split results by thread
"""
import csv

from backend.lib.processor import BasicProcessor, ProcessorDescription
from common.lib.compatibility import Compatibility
from common.lib.outputs import Archive

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
	description = ProcessorDescription(
		title="Split by thread",
		category="Conversion",
		description="Split the dataset into one file per thread, keeping only the posts in each thread.",
		icon="scissors",
	)
	extension = "zip"  # extension of result file, used internally and in UI

	# a zip archive of data files
	output = Archive()

	# datasets with a thread structure (4chan/8chan, reddit, breitbart)
	compatibility = Compatibility(datasources={"fourchan", "eightchan", "reddit", "breitbart"})

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with unique usernames and in the other one the amount
		of posts for that user name
		"""
		# prepare staging area
		results_path = self.dataset.get_staging_area()

		# read and write
		self.dataset.update_status("Creating separate thread files")
		for post in self.source_dataset.iterate_items(self):
			thread = results_path.joinpath(post["thread_id"] + ".csv")
			new = not thread.exists()

			with thread.open("a", encoding="utf-8") as output:
				output_csv = csv.DictWriter(output, fieldnames=post.keys())

				if new:
					output_csv.writeheader()

				output_csv.writerow(post)

		self.write_archive_and_finish(results_path)