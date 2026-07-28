"""
View .metadata.json

Designed to work with any processor that has a 'map_metadata' method
"""
import csv

from backend.lib.processor import BasicProcessor
from common.lib.compatibility import Compatibility
from common.lib.dataset import DataSet
from common.lib.exceptions import DataSetException, MetadataException, ProcessorInterruptedException
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
		Read .metadata.json from the parent archive and reformat as CSV using the
		parent producer's `map_metadata` / `map_failure_metadata` hooks, adding
		the data of the dataset the media was downloaded from where that dataset
		can still be found.
		"""
		self.dataset.update_status("Collecting .metadata.json file")
		try:
			metadata = self.source_dataset.read_media_metadata()
		except FileNotFoundError:
			self.dataset.finish_with_error("Unable to identify metadata file")
			return
		except MetadataException as e:
			self.dataset.finish_with_error(f"Unable to read metadata: {e}")
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
		source_columns, source_items = [], {}
		if self.parameters.get("join_source", True) and wanted_ids:
			source_columns, source_items = self.collect_source_data(metadata, wanted_ids)

		self.write_rows(media_rows, source_columns, source_items)

	def collect_media_rows(self, metadata, producer):
		"""
		Turn the metadata file into rows

		The processor that made the archive decides what the rows look like, via
		its `map_metadata` and `map_failure_metadata` methods. Their columns are
		prefixed here so that they cannot collide with those of the dataset the
		media came from.

		:param MediaArchiveMetadata metadata:  The archive's metadata
		:param producer:  Processor class that made the archive
		:return tuple:  A list of (row, item IDs) tuples, and the set of all
		  item IDs those rows refer to
		"""
		media_rows = []
		wanted_ids = set()

		def add(rows, entry):
			# a download that produced no file still records the items it was
			# for, so failures can be traced back to an item as well
			post_ids = list(dict.fromkeys(str(post_id).strip() for post_id in entry.get("post_ids", [])))
			for row in rows:
				media_rows.append(({self.media_prefix + column: cell for column, cell in row.items()}, post_ids))
				wanted_ids.update(post_ids)

		for filename, item in metadata.iter_entries():
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while reading metadata file")
			add(producer.map_metadata(filename, item), item)

		map_failure = getattr(producer, "map_failure_metadata", None)
		if self.parameters.get("include_failed", False) and map_failure is not None:
			for failure in metadata.iter_failures():
				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while reading metadata file")
				add(map_failure(failure), failure)

		return media_rows, wanted_ids

	def collect_source_data(self, metadata, wanted_ids):
		"""
		Read the items the media was downloaded from

		More than one dataset can look like the right one to use, so each is
		tried in turn and the first that actually accounts for some of the media
		is used. If none of them do, the best guess is still used, so that the
		result has its columns and the mismatch is reported rather than passing
		silently.

		:param MediaArchiveMetadata metadata:  The archive's metadata
		:param set wanted_ids:  IDs of the items the media refers to
		:return tuple:  The columns to add, and a map of item ID to the values
		  of those columns; both empty if there is no dataset to use
		"""
		fallback = None
		for candidate, found_via in self.find_origin_datasets(metadata):
			columns = candidate.get_columns()
			if not columns:
				# e.g. an archive, or an NDJSON file whose items cannot be read
				# as columns: there is nothing to add from this one
				self.dataset.log(f"Dataset {candidate.key} ({found_via}) has no readable columns; skipping it")
				continue

			self.dataset.update_status(f"Combining metadata with dataset '{candidate.get_label()}'")
			items = self.collect_source_items(candidate, columns, wanted_ids)
			if items:
				self.dataset.log(f"Adding data from dataset {candidate.key} ({found_via}); "
								 f"accounts for {len(items):,} of {len(wanted_ids):,} item(s) the media refers to")
				return columns, items

			self.dataset.log(f"Dataset {candidate.key} ({found_via}) has none of the items the media refers to")
			if fallback is None:
				fallback = (columns, {})

		if fallback is not None:
			return fallback

		self.dataset.log("Could not find the dataset the media was downloaded from; writing metadata only")
		return [], {}

	def find_origin_datasets(self, metadata):
		"""
		Find the datasets the media in this archive may have been downloaded from

		The metadata file records the key of that dataset, which is normally the
		right one, but it can name a helper dataset that a preset built for the
		downloader rather than the dataset a researcher would recognise. As a
		second option, walk up the chain of parent datasets, skipping any that
		are media archives themselves - an archive can be made from another
		archive, for example by filtering out duplicate images.

		:param MediaArchiveMetadata metadata:  The archive's metadata
		:return list:  (dataset, how it was found) tuples, best guess first
		"""
		candidates = []

		if metadata.from_dataset:
			try:
				recorded = DataSet(key=metadata.from_dataset, db=self.db, modules=self.modules)
				if recorded.is_finished() and recorded.num_rows:
					candidates.append((recorded, "recorded in the metadata file"))
			except DataSetException:
				# deleted since the media was downloaded
				pass

		parent = self.source_dataset.get_parent()
		while parent is not None and self.is_media_archive(parent):
			parent = parent.get_parent()
		if parent is not None and parent.num_rows and parent.key not in [c.key for c, _ in candidates]:
			candidates.append((parent, "found by walking up the chain of parent datasets"))

		return candidates

	def collect_source_items(self, dataset, columns, wanted_ids):
		"""
		Read the wanted items from a dataset in one pass

		Only items the media refers to are kept, so the amount of data held here
		depends on the size of the archive and not on that of the dataset.

		:param DataSet dataset:  Dataset to read
		:param list columns:  Columns to keep
		:param set wanted_ids:  IDs of the items to keep
		:return dict:  Item ID to the values of those columns
		"""
		found = {}
		for items_read, item in enumerate(dataset.iterate_items(self)):
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while reading source dataset")

			for post_id in self.item_ids(item):
				if post_id in wanted_ids and post_id not in found:
					found[post_id] = {column: item.get(column, "") for column in columns}

			if len(found) == len(wanted_ids):
				# every item the media refers to has been found
				break

			if items_read and items_read % 500 == 0:
				self.dataset.update_status(f"Looked for media in {items_read:,} of {dataset.num_rows:,} item(s)")

		return found

	def write_rows(self, media_rows, source_columns, source_items):
		"""
		Write the result file and finish the dataset

		A media file used by several items becomes one row per item, so that
		nothing has to be merged into one cell. One that cannot be traced back to
		an item still gets a row, with the source columns left empty.

		:param list media_rows:  Rows as returned by `collect_media_rows`
		:param list source_columns:  Columns to add from the source dataset
		:param dict source_items:  Item ID to source column values
		"""
		fieldnames, source_column_map = self.build_fieldnames(media_rows, source_columns)
		num_rows = 0
		matched = 0

		with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile:
			writer = csv.DictWriter(outfile, fieldnames=fieldnames, restval="", extrasaction="ignore")
			writer.writeheader()

			for row, post_ids in media_rows:
				items = [source_items[post_id] for post_id in post_ids if post_id in source_items]

				if not items:
					if source_columns:
						row = {**row, self.matched_column: False}
					writer.writerow(remove_nuls(row))
					num_rows += 1
					continue

				matched += 1
				for item in items:
					writer.writerow(remove_nuls({
						**row,
						self.matched_column: True,
						**{source_column_map[column]: value for column, value in item.items()}
					}))
					num_rows += 1

		if source_columns:
			self.dataset.log(f"Traced {matched:,} of {len(media_rows):,} metadata row(s) back to an item")

		self.dataset.update_status(f"Read metadata for {num_rows:,} item(s).")

		if source_columns and not matched:
			self.dataset.finish_with_warning(
				num_rows,
				f"Wrote {num_rows:,} metadata row(s), but none of them could be traced back to an item in the "
				f"dataset the media was downloaded from; its columns are empty."
			)
		else:
			self.dataset.finish(num_rows)

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

	@classmethod
	def is_media_archive(cls, module):
		"""
		Is this dataset an archive of downloaded media files?

		:param module:  Dataset or processor to check
		:return bool:
		"""
		return any(module.type.startswith(prefix) for prefix in cls.media_archive_prefixes)

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
