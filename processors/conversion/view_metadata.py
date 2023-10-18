"""
View .metadata.json

Designed to work with any processor that has a 'map_metadata' method
"""
import json
import zipfile

from backend.lib.processor import BasicProcessor
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
	def is_compatible_with(cls, module=None, user=None):
		"""
		Determine if processor is compatible with dataset

		:param module: Module to determine compatibility with
		"""
		return module.type.startswith("video-downloader") or module.type.startswith("image-downloader")

	def process(self):
		"""
		Grabs .metadata.json and reformats
		"""
		self.dataset.update_status("Collecting .metadata.json file")
		with zipfile.ZipFile(self.source_file, "r") as archive_file:
			archive_contents = sorted(archive_file.namelist())
			if '.metadata.json' not in archive_contents:
				self.dataset.update_status("Unable to identify metadata file", is_final=True)
				self.dataset.finish(0)
				return

			staging_area = self.dataset.get_staging_area()
			archive_file.extract(".metadata.json", staging_area)

			with open(staging_area.joinpath(".metadata.json")) as file:
				metadata_file = json.load(file)

		parent_processor = self.dataset.get_parent().get_own_processor()
		if parent_processor is None or not hasattr(parent_processor, "map_metadata"):
			if parent_processor is not None:
				self.log.warning(f"Metadata formatter processor cannot run on {parent_processor.type}; map_metadata method not implemented")
			self.dataset.update_status("Cannot reformat metadata for this dataset", is_final=True)
			self.dataset.finish(0)
			return
		self.dataset.log(f"Collecting metadata created by {parent_processor.type}")

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
