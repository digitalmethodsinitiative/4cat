"""
Filter by pseudo-random posts
"""
import random

from backend.lib.processor import BasicProcessor, ProcessorDescription
from processors.filtering.base_filter import BaseFilter
from common.lib.compatibility import Compatibility
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
	description = ProcessorDescription(
		title="Random sample",
		category="Filtering",
		tags=["sample"],
		description="Retain a pseudo-random sample of a chosen number of items from the dataset. This creates a new dataset containing the sampled items.",
	)

	# Allow on top-level CSV/NDJSON/ZIP datasets
	compatibility = Compatibility(top_dataset_only=True, extensions={"csv", "ndjson", "zip"})

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
				"default": 10,
				"coerce": int,
			}
		}

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
			self.dataset.finish_with_error("Could not determine the number of items in the source dataset.")
			return
		dataset_size = int(dataset_size)

		# Get the amount of rows to sample
		sample_size = self.parameters.get("sample_size")

		try:
			sample_size = int(sample_size)
		except ValueError:
			self.dataset.finish_with_error("The sample size must be a valid whole number.")
			return
		if not sample_size:
			self.dataset.finish_with_error("The sample size must be greater than zero.")
			return
		elif sample_size > dataset_size:
			self.dataset.finish_with_error("The sample size cannot be larger than the number of items in the dataset.")
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
					self.dataset.update_status(f"Sampled {written:,}/{sample_size:,} items")

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
	
class RandomProcessorFilter(RandomFilter):
    """
    Retain only posts where a given column matches a given value
    """
    type = "random-processor-filter"  # job type ID
    description = ProcessorDescription(
        title="Random sample",
        category="Filtering",
        tags=["sample"],
        description="Retain a pseudo-random sample of a chosen number of items from the dataset. This creates a new dataset containing the sampled items.",
    )

    # child (non-top-level) csv/ndjson/zip datasets
    compatibility = Compatibility(child_only=True, extensions={"csv", "ndjson", "zip"})

    @classmethod
    def is_filter(cls):
        """
        I'm a filter! And so are my children.
        """
		# We lie here because `is_filter()` is doing too much work (i.e. also used to determine if the dataset is top-level).
        return False

    @classmethod
    def get_extension(cls, parent_dataset=None):
        # We write the parent's file format verbatim into the result file
        # (see BaseFilter.process), so the dataset must be created with the
        # parent's extension — not the BasicProcessor default of "csv". We
        # can't rely on the is_filter() branch in BasicProcessor.get_extension
        # because we deliberately report is_filter() == False for UI purposes.
        if parent_dataset is not None:
            return parent_dataset.get_extension()
        return None

    def after_process(self):
        BasicProcessor.after_process(self)
        # Inherit the source dataset's type and datasource so map_item resolves
        # correctly on the filtered result (especially for NDJSON). Unlike
        # BaseFilter, we deliberately keep this dataset attached to its parent
        # rather than promoting it to a standalone top-level dataset.
        self.dataset.adopt_type(self.source_dataset.type)
        self.dataset.change_datasource(
            self.source_dataset.parameters.get("datasource", self.source_dataset.type)
        )
