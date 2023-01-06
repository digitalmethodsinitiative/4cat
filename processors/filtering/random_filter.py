"""
Filter by pseudo-random posts
"""
import random

from processors.filtering.base_filter import BaseFilter
from common.lib.helpers import UserInput

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


class RandomFilter(BaseFilter):
	"""
	Retain a pseudo-random amount of posts
	"""
	type = "random-filter"  # job type ID
	category = "Filtering"  # category
	title = "Random sample"  # title displayed in UI
	description = "Retain a pseudorandom set of posts. This creates a new dataset."  # description displayed in UI

	# the following determines the options available to the user via the 4CAT interface
	options = {
		"sample_size": {
			"type": UserInput.OPTION_TEXT,
			"help": "Sample size",
			"default": ""
		}
	}

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor on NDJSON and CSV files

		:param module: Dataset or processor to determine compatibility with
		"""
		return module.is_top_dataset() and module.get_extension() in ("csv", "ndjson")

	def filter_items(self):
		"""
		Create a generator to iterate through items that can be passed to create either a csv or ndjson. Use
		`for original_item, mapped_item in self.source_dataset.iterate_mapped_items(self)` to iterate through items
		and yield `original_item`.

		:return generator:
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
		count = 0  # To check whether we've reachted the matching row
		written = 0  # Serves as an index for the next matching row
		match_row = posts_to_keep[0]  # The row count of the first matching row

		# Iterate through posts and keep those in the match list
		for original_item, mapped_item in self.source_dataset.iterate_mapped_items(self):

			# Yield on match
			if count == match_row:
				written += 1
				if count != (dataset_size - 1) and written < sample_size:
					match_row = posts_to_keep[written]
				yield original_item

				if written % max(int(sample_size/10), 1) == 0:
					self.dataset.update_status("Wrote %i posts" % written)

			count += 1
