"""
View .metadata.json

Designed to work with any processor that has a 'map_metadata' method
"""
from backend.lib.processor import BasicProcessor
from common.lib.exceptions import MetadataException
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
	title = "View media metadata"  # title displayed in UI
	description = "Reformats the .metadata.json file and calculates analytics"  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

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

	@classmethod
	def is_compatible_with(cls, module=None, config=None):
		"""
		Determine if processor is compatible with dataset

		:param module: Module to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
		"""
		return module.type.startswith("video-downloader") or module.type.startswith("image-downloader")

	def process(self):
		"""
		Read .metadata.json from the parent archive and reformat as CSV using
		the parent producer's `map_metadata` / `map_failure_metadata` hooks.
		"""
		self.dataset.update_status("Collecting .metadata.json file")
		try:
			metadata = self.dataset.get_parent().read_media_metadata()
		except FileNotFoundError:
			self.dataset.finish_with_error("Unable to identify metadata file")
			return
		except MetadataException as e:
			self.dataset.finish_with_error(f"Unable to read metadata: {e}")
			return

		parent_processor = self.dataset.get_parent().get_own_processor()
		if parent_processor is None or not hasattr(parent_processor, "map_metadata"):
			if parent_processor is not None:
				self.log.warning(f"Metadata formatter processor cannot run on {parent_processor.type}; map_metadata method not implemented")
			self.dataset.finish_with_error("Cannot reformat metadata for this dataset")
			return
		self.dataset.log(f"Collecting metadata created by {parent_processor.type}")

		include_failed = self.parameters.get("include_failed", False)
		map_failure = getattr(parent_processor, "map_failure_metadata", None)
		rows = []
		num_posts = 0

		for filename, item in metadata.iter_entries():
			for row in parent_processor.map_metadata(filename, item):
				rows.append(row)
				num_posts += 1

		if include_failed and map_failure is not None:
			for failure in metadata.iter_failures():
				for row in map_failure(failure):
					rows.append(row)
					num_posts += 1

		# Finish up
		self.dataset.update_status(f"Read metadata for {num_posts:,} item(s).")

		if rows:
			self.write_csv_items_and_finish(rows)
		else:
			return self.dataset.finish_with_error("No valid metadata could be read from the dataset.")
