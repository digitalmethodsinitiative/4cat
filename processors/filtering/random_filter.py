"""
Filter by pseudo-random posts
"""
import random

from processors.filtering.base_filter import BaseFilter
from common.lib.helpers import UserInput
from common.lib.exceptions import QueryParametersException

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

	@classmethod
	def get_options(cls, parent_dataset=None, config=None) -> dict:
		"""
		Get processor options

		:param parent_dataset DataSet:  An object representing the dataset that
			the processor would be or was run on. Can be used, in conjunction with
			config, to show some options only to privileged users.
		:param config ConfigManager|None config:  Configuration reader (context-aware)
		:return dict:   Options for this processor
		"""
		return {
			"sample_size": {
				"type": UserInput.OPTION_TEXT,
				"help": "Sample size",
				"default": ""
			}
		}

	@classmethod
	def is_compatible_with(cls, module=None, config=None):
		"""
		Allow processor on NDJSON and CSV files

		:param module: Module to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
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
			return
		dataset_size = int(dataset_size)

		# Get the amount of rows to sample
		sample_size = self.parameters.get("sample_size")

		try:
			sample_size = int(sample_size)
		except ValueError:
			self.dataset.finish_with_error("Use a valid integer as a sample size")
			return
		if not sample_size:
			self.dataset.finish_with_error("Invalid sample size %s" % sample_size)
			return
		elif sample_size > dataset_size:
			self.dataset.finish_with_error("The sample size can't be larger than the dataset size")
			return

		# keep some stats
		posts_to_keep = sorted(random.sample(range(0, dataset_size), sample_size))
		count = 0  # To check whether we've reachted the matching row
		written = 0  # Serves as an index for the next matching row
		match_row = posts_to_keep[0]  # The row count of the first matching row

		# Iterate through posts and keep those in the match list
		for mapped_item in self.source_dataset.iterate_items(processor=self, get_annotations=False):

			# Yield on match
			if count == match_row:
				written += 1
				if count != (dataset_size - 1) and written < sample_size:
					match_row = posts_to_keep[written]

				yield mapped_item

				if written % max(int(sample_size/10), 1) == 0:
					self.dataset.update_status("Wrote %i posts" % written)

			count += 1


	@staticmethod
	def validate_query(query, request, config):
		"""
		Validate input

		Checks if everything needed is filled in.

		:param query:
		:param request:
		:param config:
		:return:
		"""

		if not query["sample_size"] or not query["sample_size"].isnumeric() or not int(query["sample_size"]) > 0:
			raise QueryParametersException("Please enter a valid sample size.")

		return query
