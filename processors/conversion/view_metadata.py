"""
View .metadata.json

Designed to work with any processor that has a 'map_metadata' method
"""
import csv
import json
import zipfile

from backend.lib.processor import BasicProcessor
from common.lib.compatibility import Compatibility
from common.lib.dataset import DataSet
from common.lib.exceptions import DataSetException, ProcessorInterruptedException
from common.lib.helpers import remove_nuls
from common.lib.user_input import UserInput

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class ViewMetadata(BasicProcessor):
	"""
	Metadata Viewer

	Reformats the .metadata.json file of a media archive and, where possible,
	adds the data of the dataset items each media file was downloaded from.
	"""
	type = "metadata-viewer"  # job type ID
	category = "Conversion"  # category
	title = "View media metadata"  # title displayed in UI
	description = "Reformats the .metadata.json file and adds the data of the items the media was downloaded from"  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	# Archives made by these processors contain a .metadata.json file. Also used
	# when looking for the dataset the media came from, because a media archive
	# can be made from another media archive (e.g. by filtering out duplicates).
	media_archive_prefixes = {"video-downloader", "image-downloader"}

	# Allow on downloaded media datasets
	compatibility = Compatibility(type_prefixes=media_archive_prefixes)

	# The columns read from the metadata file get this prefix, so that they
	# cannot collide with the columns of the dataset the media came from.
	media_prefix = "media_"

	# Says whether a row could be traced back to an item in that dataset. Only
	# written when there is a dataset to combine the metadata with.
	matched_column = "media_source_matched"

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
			"join_source": {
				"type": UserInput.OPTION_TOGGLE,
				"help": "Add data of the items the media came from",
				"default": True,
				"tooltip": "If enabled, each media file is combined with the item(s) it was downloaded from, so "
						   "that for example the text of a post is shown next to the image found in it. Media "
						   "files that cannot be traced back to an item are still included, with empty columns."
			},
			"include_failed": {
				"type": UserInput.OPTION_TOGGLE,
				"help": "Included failed datapoints",
				"default": False,
				"tooltip": "If enabled, rows that failed will also be included (e.g., due to errors et cetera)."
			},
		}

	def process(self):
		"""
		Grabs .metadata.json, reformats it, and combines it with the dataset the
		media was downloaded from where that dataset can still be found.
		"""
		metadata = self.read_metadata_file()
		if metadata is None:
			return

		producer = self.source_dataset.get_own_processor()
		if producer is None or not hasattr(producer, "map_metadata"):
			if producer is not None:
				self.log.warning(f"Metadata formatter processor cannot run on {producer.type}; map_metadata method not implemented")
			self.dataset.finish_with_error("Cannot reformat metadata for this dataset")
			return
		self.dataset.log(f"Collecting metadata created by {producer.type}")

		# read the metadata file into rows, and note which items they refer to
		media_rows, wanted_ids = self.collect_media_rows(metadata, producer)
		if not media_rows:
			return self.dataset.finish_with_error("No valid metadata could be read from the dataset.")

		# find the dataset the media was downloaded from, if there is one left
		source_dataset = None
		source_columns = []
		if self.parameters.get("join_source", True) and wanted_ids:
			source_dataset, found_via = self.find_origin_dataset(metadata)
			if source_dataset:
				source_columns = source_dataset.get_columns()
				if source_columns:
					self.dataset.update_status(f"Combining metadata with dataset '{source_dataset.get_label()}'")
					self.dataset.log(f"Adding data from dataset {source_dataset.key} ({found_via})")
				else:
					# e.g. an archive, or an NDJSON file whose items cannot be
					# read as columns: there is nothing to add
					self.dataset.log(f"Dataset {source_dataset.key} has no readable columns; writing metadata only")
					source_dataset = None

		fieldnames, source_column_map = self.build_fieldnames(media_rows, source_columns)
		matched_rows = set()
		num_rows = 0

		with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile:
			writer = csv.DictWriter(outfile, fieldnames=fieldnames, restval="", extrasaction="ignore")
			writer.writeheader()

			if source_dataset:
				# One pass over the source dataset. Only items that a media file
				# refers to are used.
				item_index = {}
				for row_index, (_, post_ids) in enumerate(media_rows):
					for post_id in post_ids:
						item_index.setdefault(post_id, []).append(row_index)

				seen_ids = set()
				items_read = 0
				for item in source_dataset.iterate_items(self):
					if self.interrupted:
						raise ProcessorInterruptedException("Interrupted while reading source dataset")

					for post_id in self.item_ids(item):
						if post_id not in item_index or post_id in seen_ids:
							# not referred to by any media file, or the item ID
							# occurs more than once in the dataset
							continue
						seen_ids.add(post_id)

						item_columns = {written_as: item.get(column, "")
										for column, written_as in source_column_map.items()}
						# a media file used by several items becomes one row per
						# item, so that nothing has to be merged into one cell
						for row_index in item_index[post_id]:
							writer.writerow(remove_nuls({
								**media_rows[row_index][0],
								self.matched_column: True,
								**item_columns
							}))
							matched_rows.add(row_index)
							num_rows += 1

					if len(seen_ids) == len(item_index):
						# every item referred to has been found
						break

					items_read += 1
					if items_read % 500 == 0:
						self.dataset.update_status(f"Looked for media in {items_read:,} of "
												   f"{source_dataset.num_rows:,} item(s)")

			# media files that could not be traced back to an item still get a
			# row, with the columns of the source dataset left empty
			for row_index, (row, _) in enumerate(media_rows):
				if row_index in matched_rows:
					continue
				if source_dataset:
					row = {**row, self.matched_column: False}
				writer.writerow(remove_nuls(row))
				num_rows += 1

		if source_dataset:
			self.dataset.log(f"Traced {len(matched_rows):,} of {len(media_rows):,} metadata row(s) back to an item "
							 f"in dataset {source_dataset.key}")

		self.dataset.update_status(f"Read metadata for {num_rows:,} item(s).")

		if source_dataset and not matched_rows:
			self.dataset.finish_with_warning(
				num_rows,
				f"Wrote {num_rows:,} metadata row(s), but none of them could be traced back to an item in the "
				f"dataset the media was downloaded from; its columns are empty."
			)
		else:
			self.dataset.finish(num_rows)

	def read_metadata_file(self):
		"""
		Read the .metadata.json file from the archive this processor runs on

		:return dict:  The metadata file's contents, or `None` if it could not
		  be read, in which case the dataset is finished with an error.
		"""
		self.dataset.update_status("Collecting .metadata.json file")
		with zipfile.ZipFile(self.source_file, "r") as archive_file:
			if ".metadata.json" not in archive_file.namelist():
				self.dataset.finish_with_error("Unable to identify metadata file")
				return None

			staging_area = self.dataset.get_staging_area()
			archive_file.extract(".metadata.json", staging_area)

		with staging_area.joinpath(".metadata.json").open() as file:
			return json.load(file)

	def collect_media_rows(self, metadata, producer):
		"""
		Turn the metadata file into rows

		The processor that made the archive decides what the rows look like, via
		its `map_metadata` method. Their columns are prefixed here so that they
		cannot collide with those of the dataset the media came from.

		:param dict metadata:  Contents of the metadata file
		:param producer:  Processor class that made the archive
		:return tuple:  A list of (row, item IDs) tuples, and the set of all
		  item IDs those rows refer to
		"""
		include_failed = self.parameters.get("include_failed", False)
		media_rows = []
		wanted_ids = set()

		for key, value in metadata.items():
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while reading metadata file")

			if not isinstance(value, dict):
				# metadata files can be uploaded by users, so may be malformed
				continue

			if not include_failed and not value.get("success", True):
				continue

			# some processors write item IDs as text and others as numbers
			post_ids = value.get("post_ids") or []
			if isinstance(post_ids, (str, int)):
				post_ids = [post_ids]
			post_ids = [str(post_id).strip() for post_id in post_ids]
			entry = {**value, "post_ids": post_ids}

			# an item referred to twice would otherwise produce the same row twice
			unique_ids = list(dict.fromkeys(post_ids))

			# Metadata may contain more than one row/item per key, value pair
			for row in producer.map_metadata(key, entry):
				prefixed = {self.media_prefix + column: cell for column, cell in row.items()}
				media_rows.append((prefixed, unique_ids))
				wanted_ids.update(unique_ids)

		return media_rows, wanted_ids

	def build_fieldnames(self, media_rows, source_columns):
		"""
		Work out the columns of the result file

		All columns are collected up front because rows do not all have the same
		ones: a media file that could not be traced back to an item has no
		columns from the source dataset, and some processors write a column only
		for the media files it applies to.

		:param list media_rows:  Rows as returned by `collect_media_rows`
		:param list source_columns:  Columns of the dataset the media came from,
		  or an empty list if there is none to combine the metadata with
		:return tuple:  Column names in the order they are written, and a map of
		  source dataset column name to the column it is written as
		"""
		fieldnames = []
		for row, _ in media_rows:
			# TODO: look into MediaArchive class PR to see if this can be removed
			fieldnames.extend(column for column in row if column not in fieldnames)

		if not source_columns:
			return fieldnames, {}

		fieldnames.append(self.matched_column)
		source_column_map = {}
		for column in source_columns:
			written_as = column
			if written_as in fieldnames:
				# the source dataset happens to have a column of its own by this
				# name; rename it rather than overwrite the metadata column
				written_as = f"source_{column}"
				self.dataset.log(f"Source dataset column '{column}' written as '{written_as}' to avoid a clash "
								 f"with the metadata column of the same name")
			source_column_map[column] = written_as
			fieldnames.append(written_as)

		return fieldnames, source_column_map

	def find_origin_dataset(self, metadata):
		"""
		Find the dataset the media in this archive was downloaded from

		The metadata file records the key of that dataset, which is the most
		reliable answer, but it may have been deleted since (e.g. a filter 
		was removed). Walk up the chain of parent datasets.

		:param dict metadata:  Contents of the metadata file
		:return tuple:  The dataset and a short description of how it was found,
		  or `(None, None)` if there is none that can be used
		"""
		recorded_keys = dict.fromkeys(value["from_dataset"] for value in metadata.values()
									  if isinstance(value, dict) and value.get("from_dataset"))
		if len(recorded_keys) > 1:
			# I do not think this is possible and can be removed with MediaArchive class PR
			self.dataset.log(f"Metadata refers to more than one source dataset ({', '.join(recorded_keys)}); "
							 f"using the first one that can be read")

		for key in recorded_keys:
			try:
				candidate = DataSet(key=key, db=self.db, modules=self.modules)
			except DataSetException:
				# deleted since the media was downloaded
				continue
			if candidate.is_finished() and candidate.num_rows:
				return candidate, "recorded in the metadata file"

		candidate = self.source_dataset.get_parent()
		while candidate is not None and self.is_media_archive(candidate):
			candidate = candidate.get_parent()
		if candidate is not None and candidate.num_rows:
			return candidate, "found by walking up the chain of parent datasets"

		self.dataset.log("Could not find the dataset the media was downloaded from; writing metadata only")
		return None, None

	@classmethod
	def is_media_archive(cls, dataset):
		"""
		Is this dataset an archive of downloaded media files?

		# TODO: Remove with MediaArchive class PR

		:param DataSet dataset:  Dataset to check
		:return bool:
		"""
		return any(dataset.type.startswith(prefix) for prefix in cls.media_archive_prefixes)

	@staticmethod
	def item_ids(item):
		"""
		Get the IDs a dataset item can be referred to by

		Media downloaders record the `id` of the item a file was found in, or
		the values of its `ids` column for datasets that combine several
		original items into one row.

		:param item:  Mapped dataset item
		:return list:  Item IDs, as text
		"""
		if "ids" in item:
			return [str(item_id).strip() for item_id in str(item.get("ids", "")).split(",")]

		return [str(item.get("id", "")).strip()]
