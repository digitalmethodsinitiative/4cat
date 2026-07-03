"""
View .metadata.json

Designed to work with any processor that has a 'map_metadata' method
"""
import json
import zipfile

from backend.lib.processor import BasicProcessor, ProcessorDescription
from common.lib.compatibility import Compatibility
from common.lib.outputs import Table
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
	description = ProcessorDescription(
		title="View media metadata",
		category="Conversion",
		description="Read the .metadata.json file produced by an image or video downloader and turn it into a flat table, with one row per downloaded item. Optionally include items whose download failed.",
		icon="circle-info",
	)
	extension = "csv"  # extension of result file, used internally and in UI
	# a derived table
	output = Table()

	# Allow on downloaded media datasets
	compatibility = Compatibility(type_prefixes={"video-downloader", "image-downloader"})

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
			"include_failed": {
				"type": UserInput.OPTION_TOGGLE,
				"help": "Included failed datapoints",
				"default": False,
				"tooltip": "If enabled, rows that failed will also be included (e.g., due to errors et cetera)."
			},
		}

	def process(self):
		"""
		Grabs .metadata.json and reformats
		"""
		self.dataset.update_status("Collecting .metadata.json file")
		with zipfile.ZipFile(self.source_file, "r") as archive_file:
			archive_contents = sorted(archive_file.namelist())
			if '.metadata.json' not in archive_contents:
				self.dataset.finish_with_error("Unable to identify metadata file")
				return

			staging_area = self.dataset.get_staging_area()
			archive_file.extract(".metadata.json", staging_area)

			with open(staging_area.joinpath(".metadata.json")) as file:
				metadata_file = json.load(file)

		parent_processor = self.dataset.get_parent().get_own_processor()
		if parent_processor is None or not hasattr(parent_processor, "map_metadata"):
			if parent_processor is not None:
				self.log.warning(f"Metadata formatter processor cannot run on {parent_processor.type}; map_metadata method not implemented")
			self.dataset.finish_with_error("Cannot reformat metadata for this dataset")
			return
		self.dataset.log(f"Collecting metadata created by {parent_processor.type}")

		include_failed = self.parameters.get("include_failed", False)
		rows = []
		num_posts = 0
		with self.dataset.get_results_path().open("w", encoding="utf-8", newline=""):
			for key, value in metadata_file.items():
				if not include_failed and not value.get("success", True):
					continue

				# Metadata may contain more than one row/item per key, value pair
				for item in parent_processor.map_metadata(key, value):
					rows.append(item)
					num_posts += 1

		# Finish up
		self.dataset.update_status(f"Read metadata for {num_posts:,} item(s).")
	
		if rows:
			self.write_csv_items_and_finish(rows)
		else:
			return self.dataset.finish_with_error("No valid metadata could be read from the dataset.")
