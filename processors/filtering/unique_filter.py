"""
Filter by unique posts
"""
import hashlib

from processors.filtering.base_filter import BaseFilter
from common.lib.helpers import UserInput

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


class UniqueFilter(BaseFilter):
	"""
	Retain only posts matching a given lexicon
	"""
	type = "unique-filter"  # job type ID
	category = "Filtering"  # category
	title = "Filter for unique posts"  # title displayed in UI
	description = "Retain posts with a unique body text. Only keeps the first encounter of a text. Useful for filtering spam. This creates a new dataset."  # description displayed in UI

	# the following determines the options available to the user via the 4CAT
	# interface.
	options = {
		"case_sensitive": {
			"type": UserInput.OPTION_TOGGLE,
			"help": "Case sensitive",
			"default": False,
			"tooltip": "Selecting this will e.g. consider 'Cat' and and 'cat' as different."
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

		# keep some stats
		processed = 0
		unique = 0

		hashes = set()

		# iterate through posts and see if they match
		for original_item, mapped_item in self.source_dataset.iterate_mapped_items(self):

			if not mapped_item.get("body", None):
				continue

			body = mapped_item["body"].strip()
			if not self.parameters.get("case_sensitive", False):
				body = body.lower()

			hash_object = hashlib.md5(body.encode("utf-8"))
			md5_hash = hash_object.hexdigest()

			if md5_hash not in hashes:
				unique += 1
				yield original_item

			hashes.add(md5_hash)

			if processed % 2500 == 0:
				self.dataset.update_status("Processed %i posts (%i unique)" % (processed, unique))
				self.dataset.update_progress(processed / self.source_dataset.num_rows)

			processed += 1
