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
	A failure hit carries every failure recorded for the URL, as
	`(metadata, failure)` pairs, so that a consumer can see not only why each
	attempt failed but which dataset made it - and therefore what settings it
	ran with, since a dataset stores the parameters it was created with.
	"""

	def __init__(self, is_success, metadata=None, entries=None, failures=None):
		self.is_success = is_success
		self.metadata = metadata
		self.entries = entries or []
		self.failures = failures or []

	@property
	def reasons(self) -> set:
		"""
		The failure reasons seen for this URL across all previous archives.

		:return set:  reason codes, e.g. `{"not_a_video"}`
		"""
		return {failure.get("reason") for _, failure in self.failures if failure.get("reason")}

	def datasets_for_reason(self, reason) -> list:
		"""
		The datasets whose archives recorded a given failure reason for this URL.

		Use this to compare a previous attempt's settings against the current
		run's: each dataset stores the parameters it ran with, so nothing about
		those settings has to be repeated in the metadata file.

		:param str reason:  reason code to look for, e.g. `"not_a_video"`
		:return list:  the datasets that recorded it, skipping any metadata that
		  was not read from a dataset
		"""
		return [metadata.dataset for metadata, failure in self.failures
				if failure.get("reason") == reason and metadata.dataset is not None]


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
		once) and to several files within one archive (e.g. a playlist). A
		file or failed download can also be reached through more than one URL
		(e.g. a short and a long link to the same video, or a link that
		redirected): see `_urls_of`.
		"""
		index = {}
		for metadata in self.metadata_objects:
			for filename, item in metadata.iter_entries():
				for url in self._urls_of(item):
					index.setdefault(url, {"items": [], "failures": []})
					index[url]["items"].append((metadata, filename, item))
			for failure in metadata.iter_failures():
				for url in self._urls_of(failure):
					index.setdefault(url, {"items": [], "failures": []})
					index[url]["failures"].append((metadata, failure))
		return index

	@staticmethod
	def _urls_of(entry) -> list:
		"""
		All URLs that lead to an item or failed download: its `url`, and every
		URL in its `extra["other_urls"]`.

		:param dict entry:  item or failure from the metadata
		:return list:  the URLs, leaving out any that are empty or not text
		"""
		other_urls = (entry.get("extra") or {}).get("other_urls")
		if not isinstance(other_urls, list):
			other_urls = []
		return [url for url in [entry.get("url"), *other_urls] if url and isinstance(url, str)]

	@property
	def url_index(self) -> dict:
		if self._url_index is None:
			self._url_index = self._build_index()
		return self._url_index

	def find(self, url: str):
		"""
		Look up a URL across all previous downloader archives.

		Returns a `MediaLibraryHit` — a success hit if any archive
		downloaded it (including as one of a file's other URLs), otherwise a
		failure hit carrying every failure `reason` seen — or `None` if the
		URL was never seen.
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
		# something else the consumer wants to interpret), each with the archive
		# that recorded it, so the consumer can also tell which run it came from
		return MediaLibraryHit(is_success=False, failures=list(bucket["failures"]))

	def __len__(self) -> int:
		return len(self.metadata_objects)
