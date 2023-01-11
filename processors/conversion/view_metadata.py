"""
View .metadata.json

Designed to work with any processor that has a 'map_metadata' method
"""
import json

from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.user_input import UserInput

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class ViewMetadata(BasicProcessor):
	"""
	Metadata Viewer

	Reformats the .metadata.json file and calculates some basic analytics
	"""
	type = "metadata-viewer"  # job type ID
	category = "Conversion"  # category
	title = "View Metadata"  # title displayed in UI
	description = "Reformats the .metadata.json file and calculates analytics"  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	options = {
		"include_failed": {
			"type": UserInput.OPTION_TOGGLE,
			"help": "Included failed datapoints",
			"default": False,
			"tooltip": "If enabled, rows that failed will also be included (e.g., due to errors et cetera)."
		},
	}

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow on only
		"""
		# hasattr(module, "map_metadata")
		return module.type in ["video-downloader"]

	def process(self):
		"""
		Grabs .metadata.json and reformats
		"""
		metadata_file = None
		self.dataset.update_status("Collecting .metadata.json file")
		for path in self.iterate_archive_contents(self.source_file):
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while collecting metadata file")

			if path.name == '.metadata.json':
				# Keep it and move on
				with open(path) as file:
					metadata_file = json.load(file)
				break

		if metadata_file is None:
			self.dataset.update_status("Unable to identify metadata file", is_final=True)
			self.dataset.finish(0)
			return

		parent_processor = self.dataset.get_parent().get_own_processor()
		self.dataset.log(f"Collecting metadata created by {parent_processor.type}")
		if not hasattr(parent_processor, "map_metadata"):
			self.log.warning(f"Metadata formatter processor cannot run on {parent_processor.type}; has no 'map_metadata' method")
			self.dataset.update_status("Cannot reformat metadata", is_final=True)
			self.dataset.finish(0)
			return

		include_failed = self.parameters.get("include_failed", False)
		rows = []
		num_posts = 0
		with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile:
			for key, value in metadata_file.items():
				if not include_failed and not value.get("success", True):
					continue

				# Metadata may contain more than one row/item per key, value pair
				for item in parent_processor.map_metadata(key, value):
					rows.append(item)
					num_posts += 1

		# Finish up
		self.dataset.update_status('Read metadata for %i items.' % num_posts)
		self.write_csv_items_and_finish(rows)
