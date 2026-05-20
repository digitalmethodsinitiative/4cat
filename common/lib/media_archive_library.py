"""
Look up media that previous downloader runs already fetched.

When a downloader (currently the video downloader) runs, other downloaders of
the same kind may have already fetched some of the same URLs from the same
source data. `MediaArchiveLibrary` aggregates the `MediaArchiveMetadata` of
those previous runs 
"""
from common.lib.exceptions import MetadataException, DataSetException


class MediaLibraryHit:
	"""
	Result of a `MediaArchiveLibrary.find()` lookup.

	A success hit carries the archive the files live in (`metadata`, whose
	`.dataset` locates the zip) and the matching `(filename, item)` entries.
	A failure hit carries the set of failure `reasons` seen for the URL
	across all previous archives; the consumer decides what they mean.
	"""

	def __init__(self, is_success, metadata=None, entries=None, reasons=None):
		self.is_success = is_success
		self.metadata = metadata
		self.entries = entries or []
		self.reasons = reasons or set()


class MediaArchiveLibrary:
	"""
	Aggregate of `MediaArchiveMetadata` from previous downloader datasets.

	Construct via `collect()` inside a processor; the bare constructor takes
	metadata objects directly and is intended for testing.
	"""

	def __init__(self, metadata_objects, current_dataset=None):
		self.metadata_objects = list(metadata_objects)
		self.current_dataset = current_dataset
		self._url_index = None

	@classmethod
	def collect(cls, current_dataset, modules, compatible_types):
		"""
		Build a library from finished downloader datasets that share
		`current_dataset`'s source data.

		:param current_dataset:  the dataset being produced now (excluded
			from the result).
		:param modules:  module registry, used to resolve the original
			dataset of a filtered set.
		:param list compatible_types:  processor types whose archives count,
			e.g. `["video-downloader"]`.
		"""
		datasets = cls._collect_previous_downloaders(current_dataset, modules, compatible_types)
		metadata_objects = []
		for dataset in datasets:
			try:
				metadata_objects.append(dataset.read_media_metadata())
			except (FileNotFoundError, MetadataException):
				# no metadata, or unfinished/malformed — nothing to reuse
				continue

		if current_dataset is not None:
			current_dataset.log(
				f"Media library: {len(metadata_objects)} previous "
				f"{'/'.join(compatible_types)} archive(s) available for reuse"
			)
		return cls(metadata_objects, current_dataset=current_dataset)

	@staticmethod
	def _collect_previous_downloaders(current_dataset, modules, compatible_types):
		"""
		Sibling datasets of a compatible processor type, plus — if the
		current dataset's parent is a filtered copy — the downloaders of the
		dataset it was copied from. Excludes the current dataset itself.
		"""
		from common.lib.dataset import DataSet

		# kids from the parent
		parent_dataset = current_dataset.get_parent()
		downloaders = [
			child for child in parent_dataset.get_children()
			if child.type in compatible_types and child.key != current_dataset.key
		]

		# kids from the original (if filtered dataset)
		if "copied_from" in parent_dataset.parameters and parent_dataset.is_top_dataset():
			try:
				original = DataSet(key=parent_dataset.parameters["copied_from"],
								   db=current_dataset.db, modules=modules)
				downloaders += [
					child for child in original.top_parent().get_children()
					if child.type in compatible_types and child.key != current_dataset.key
				]
			except DataSetException:
				# the original dataset no longer exists
				pass

		return downloaders

	def _build_index(self) -> dict:
		"""
		`{url: {"items": [(metadata, filename, item), ...],
				"failures": [(metadata, failure), ...]}}`

		A URL can map to entries from several archives (downloaded more than
		once) and to several files within one archive (e.g. a playlist).
		"""
		index = {}
		for metadata in self.metadata_objects:
			for filename, item in metadata.iter_entries():
				url = item.get("url")
				if not url:
					continue
				index.setdefault(url, {"items": [], "failures": []})
				index[url]["items"].append((metadata, filename, item))
			for failure in metadata.iter_failures():
				url = failure.get("url")
				if not url:
					continue
				index.setdefault(url, {"items": [], "failures": []})
				index[url]["failures"].append((metadata, failure))
		return index

	@property
	def url_index(self) -> dict:
		if self._url_index is None:
			self._url_index = self._build_index()
		return self._url_index

	def find(self, url: str):
		"""
		Look up a URL across all previous downloader archives.

		Returns a `MediaLibraryHit` — a success hit if any archive
		downloaded it, otherwise a failure hit carrying every failure
		`reason` seen — or `None` if the URL was never seen.
		"""
		bucket = self.url_index.get(url)
		if not bucket:
			return None

		if bucket["items"]:
			# success beats failure; take the first archive that has the URL
			# and copy all of its files for that URL (one URL may yield many,
			# e.g. a playlist)
			first_metadata = bucket["items"][0][0]
			entries = [(filename, item) for metadata, filename, item in bucket["items"]
					   if metadata is first_metadata]
			return MediaLibraryHit(is_success=True, metadata=first_metadata, entries=entries)

		# pass all the failures (e.g. in case one is "error", but later is "not_a_video", or 
		# something else the consumer wants to interpret)
		reasons = {failure.get("reason") for _, failure in bucket["failures"]
				   if failure.get("reason")}
		return MediaLibraryHit(is_success=False, reasons=reasons)

	def __len__(self) -> int:
		return len(self.metadata_objects)
