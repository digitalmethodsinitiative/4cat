"""
Filter by pseudo-random posts
"""
import csv
import random

from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)

class RandomFilter(BasicProcessor):
	"""
	Retain a pseudo-random amount of posts
	"""
	type = "random-filter"  # job type ID
	category = "Filtering"  # category
	title = "Filter for random posts"  # title displayed in UI
	description = "Retain a pseudo-random set of posts. This creates a new, separate csv dataset you can run analyses on."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	# the following determines the options available to the user via the 4CAT
	# interface.
	options = {
		"sample_size": {
			"type": UserInput.OPTION_TEXT,
			"help": "Sample size",
			"default": ""
		}
	}

	def process(self):
		"""
		Creates a pseudo-random list of numbers within the range of a dataset length.
		Then reads a CSV file and only keeps those aligning with the list integers.
		"""

		# now for the real deal
		self.dataset.update_status("Reading source file")

		# Get the dataset size
		dataset_size = self.source_dataset.num_rows

		if not dataset_size:
			self.dataset.finish_with_error("Could not retrieve the amount of rows for the parent dataset")
		dataset_size = int(dataset_size)

		# Get the amount of rows to sample
		sample_size = self.parameters.get("sample_size")

		try:
			sample_size = int(sample_size)
		except ValueError:
			self.dataset.update_status("Use a valid integer as a sample size", is_final=True)
			self.dataset.finish(0)
			return
		if not sample_size:
			self.dataset.update_status("Invalid sample size %s" % sample_size, is_final=True)
			self.dataset.finish(0)
			return
		elif sample_size > dataset_size:
			self.dataset.update_status("The sample size can't be larger than the dataset size", is_final=True)
			self.dataset.finish(0)
			return

		# keep some stats
		posts_to_keep = sorted(random.sample(range(0, dataset_size), sample_size))

		# iterate through posts and see if they match
		with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as output:
			
			# get header row, we need to copy it for the output
			fieldnames = self.source_dataset.get_item_keys(self)

			# start the output file
			writer = csv.DictWriter(output, fieldnames=fieldnames)
			writer.writeheader()

			count = 0 # To check whether we've reachted the matching row
			written = 0 # Serves as an index for the next matching row
			match_row = posts_to_keep[0] # The row count of the first matching row 

			# Iterate through posts and keep those in the match list
			for post in self.source_dataset.iterate_items(self):
				
				# Write on match
				if count == match_row:
					writer.writerow(post)
					written += 1
					if count != (dataset_size - 1) and written < sample_size:
						match_row = posts_to_keep[written]
				
				count += 1

				if written % 2500 == 0:
					self.dataset.update_status("Wrote %i posts" % written)

		self.dataset.update_status("New dataset created with %i random rows" % written, is_final=True)
		self.dataset.finish(written)

	def after_process(self):
		super().after_process()

		# Request standalone
		self.create_standalone()
