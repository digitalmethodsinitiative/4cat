"""
Read and write metadata files packaged inside dataset archives.

4CAT processors that produce ZIP archives can include a small JSON file
describing the other files in the archive — what they are and where they came
from. This module provides `ArchiveMetadataFile`, a base class handling the
shared plumbing (locating the file inside a zip or results folder, schema
versioning, atomic writes), and `MediaArchiveMetadata`, the schema for media
download archives.

`MediaArchiveMetadata` record per media file the source post IDs,
originating URL (if any), and any platform-specific data. Download attempts
that produced no file are recorded separately as failures.

TODO:
There are other metadata files (e.g. token sets, topic models) with their own
metadata files with quite different schemas. They seem like they need their
own classes as well (or would be super redundant in `ArchiveMetadataFile` 
format).
"""
import json
import os
import zipfile
from pathlib import Path
from typing import Iterator, Optional

from common.lib.exceptions import MetadataException
from common.lib.helpers import get_software_commit


class ArchiveMetadataFile:
	"""
	Base class for JSON metadata files inside dataset archives.

	Handles only the shared plumbing: locate the file (zip member or
	results folder), read it, check the schema version, and writing it
	back. Subclasses define the actual schema by implementing
	`_populate_from_raw` and `to_dict`, and optionally `validate`.
	"""

	# Subclasses must set these.
	SCHEMA_VERSION: Optional[int] = None
	DEFAULT_FILENAME: Optional[str] = None

	def __init__(self, dataset=None, processor_type: Optional[str] = None, filename: Optional[str] = None):
		self.dataset = dataset
		# store the processor that created the archive and metadata
		# leaving optional in cases we create metadata... some other way
		self.processor_type = processor_type
		# the 4CAT version that created the metadata: resolved by `new()`
		self.software_version = None
		self.software_source = None

		# filename and schema
		self._filename = filename or self.DEFAULT_FILENAME
		self.schema_version = self.SCHEMA_VERSION

	def _resolve_software_version(self) -> None:
		"""
		Record the 4CAT commit / repository creating this metadata.

		Called by `new()` on the producer path. A no-op without a dataset to
		resolve against (e.g. metadata constructed outside a processor run).
		"""
		if self.dataset is None:
			return
		commit, source = get_software_commit(self.dataset.get_own_processor())
		self.software_version = commit
		self.software_source = source

	@classmethod
	def read(cls, dataset, *, filename: Optional[str] = None):
		"""
		Load metadata from a finished dataset's archive or results folder.

		:param dataset:  the DataSet to read from.
		:param filename:  metadata filename; defaults to the class's
			`DEFAULT_FILENAME`.

		:raises FileNotFoundError:  the metadata file is not present.
		:raises MetadataException:  the dataset is unfinished/empty, or the
			file is malformed or claims an unsupported schema version.
		"""
		filename = filename or cls.DEFAULT_FILENAME

		# for reading, we check the dataset is actually finished and has results
		results_file = dataset.check_dataset_finished()
		if results_file is None:
			raise MetadataException("Dataset is not finished; metadata may be incomplete.")
		if results_file == "empty":
			raise MetadataException("Dataset is empty; no metadata available.")

		# load it
		raw = cls._load_raw(dataset, Path(results_file), filename)
		# create the class
		instance = cls(dataset, filename=filename)
		# and populate
		instance._populate_from_raw(raw)
		return instance

	@staticmethod
	def _load_raw(dataset, results_file: Path, filename: str) -> dict:
		"""
		Locate and JSON-decode the metadata file (zip member or folder).
		"""
		# if the dataset has a zip archive, look inside it
		if results_file.suffix == ".zip":
			with zipfile.ZipFile(results_file, "r") as archive:
				if filename not in archive.namelist():
					raise FileNotFoundError(f"No metadata file {filename} in archive {results_file.name}.")
				with archive.open(filename) as f:
					return json.load(f)

		# it is possible we have a results folder w/ metadata instead; look there
		results_folder = dataset.get_results_folder_path()
		if not results_folder.is_dir():
			raise FileNotFoundError(f"No metadata file {filename} found (no results folder).")
		
		# check that the file exists
		metadata_path = results_folder / filename
		if not metadata_path.is_file():
			raise FileNotFoundError(f"No metadata file {filename} in {results_folder}.")
		
		# load the metadata!
		with open(metadata_path) as f:
			return json.load(f)

	@classmethod
	def _check_schema_version(cls, raw: dict) -> Optional[int]:
		"""
		Read the `schema_version` of a raw metadata dict.

		Returns the declared version, or None if the file predates schema
		versioning (legacy). Raises MetadataException for a version this
		class does not know how to read.

		This is meant to allow us to change the schema later if needed
		"""
		version = raw.get("schema_version")
		if version is not None and version != cls.SCHEMA_VERSION:
			raise MetadataException(
				f"Unsupported metadata schema_version {version}; expected {cls.SCHEMA_VERSION}."
			)
		return version

	# -- subclass hooks --

	def _populate_from_raw(self, raw: dict) -> None:
		"""Populate instance state from a raw decoded dict."""
		raise NotImplementedError

	def to_dict(self) -> dict:
		"""Serialise instance state to a JSON-encodable dict."""
		raise NotImplementedError

	def validate(self) -> None:
		"""Strict schema check run before writing. Override as needed."""
		pass

	# -- output --

	def write(self, staging_area, *, filename: Optional[str] = None) -> Path:
		"""
		Validate and atomically write the metadata file to
		`<staging_area>/<filename>`. Returns the path written.
		"""
		if filename is None:
			filename = self._filename

		# validate before writing; this will be a sanity check for fields (or whatever)
		self.validate()

		# write it first to a staging area, then move it to the target location 
		# should avoid leaving a half-written file if something goes wrong
		staging_area = Path(staging_area)
		target = staging_area / filename
		tmp = target.parent / (target.name + ".tmp")
		with open(tmp, "w", encoding="utf-8") as f:
			json.dump(self.to_dict(), f)
		os.replace(tmp, target)
		return target


class MediaArchiveMetadata(ArchiveMetadataFile):
	"""
	Metadata for media download archives (`.metadata.json`).

	Keyed by output filename; each item records the source post IDs, the
	originating URL (if any), and an `extra` blob of platform-specific data.
	Download attempts that produced no file are recorded in `failures`.
	"""

	SCHEMA_VERSION = 1
	DEFAULT_FILENAME = ".metadata.json"

	def __init__(self, dataset=None, *, processor_type: Optional[str] = None,
				 from_dataset: Optional[str] = None,
				 filename: Optional[str] = None):
		# `dataset` is the target dataset (the one the archive belongs to).
		# `from_dataset` is the source dataset key whose posts are being
		# downloaded from; these are not generally the same and there is no
		# safe default — producers must set it explicitly.
		super().__init__(dataset, processor_type=processor_type, filename=filename)
		# store the source dataset key (e.g. top dataset or some subdataset)
		self.from_dataset = from_dataset

		# the actual metadata content
		self.items: dict = {}
		self.failures: list = []

	# -- constructors --

	@classmethod
	def new(cls, dataset=None, *, processor_type: str,
			from_dataset: Optional[str] = None,
			filename: Optional[str] = None) -> "MediaArchiveMetadata":
		"""
		Empty container for a producer that is building an archive.

		:param dataset:  the DataSet the archive will belong to.
		:param processor_type:  producer identifier, typically `processor.type`.
		:param from_dataset:  key of the source dataset whose posts are being
			downloaded from.
		:param filename:  metadata filename inside the archive.
		"""
		instance = cls(dataset, processor_type=processor_type,
					   from_dataset=from_dataset, filename=filename)
		instance._resolve_software_version()
		return instance

	# -- schema population / legacy normalization --

	def _populate_from_raw(self, raw: dict) -> None:
		"""
		Populate fields from a raw dict. v1 is trusted as-is; older shapes
		are translated through `_normalize_legacy`.
		"""
		if not isinstance(raw, dict):
			raise MetadataException("Metadata file is not a JSON object.")

		version = self._check_schema_version(raw)
		if version == self.SCHEMA_VERSION and "items" in raw:
			self.schema_version = version
			self.from_dataset = raw.get("from_dataset", self.from_dataset)
			# pretty sure we did not store the processor or version info previously
			self.processor_type = raw.get("processor_type")
			self.software_version = raw.get("software_version")
			self.software_source = raw.get("software_source")

			self.items = dict(raw.get("items", {}))
			self.failures = list(raw.get("failures", []))
			return

		# version is None here (a mismatching version would have raised
		# above): this is a pre-schema-versioned file.
		self._normalize_legacy(raw)

	def _normalize_legacy(self, raw: dict) -> None:
		"""
		Translate pre-v1 metadata to v1.

		Old format is a flat dict keyed by URL (image/video) or filename
		(Telegram). Each entry has a `success` flag; failed entries become
		`failures[]`, successful entries become `items[filename]`. The video
		downloader's nested `files[]` list explodes to one item per file.
		"""
		for outer_key, entry in raw.items():
			if not isinstance(entry, dict):
				continue

			post_ids = entry.get("post_ids")
			if post_ids is None and "post_id" in entry:
				post_ids = [entry["post_id"]]
			post_ids = self._normalize_post_ids(post_ids)

			url = entry.get("url")
			if url is None and isinstance(outer_key, str) and (
					outer_key.startswith("http://") or outer_key.startswith("https://")):
				url = outer_key

			if self.from_dataset is None and entry.get("from_dataset"):
				self.from_dataset = entry["from_dataset"]

			success = entry.get("success", True)

			if not success:
				self.failures.append({
					"post_ids": post_ids,
					**({"url": url} if url is not None else {}),
					"reason": entry.get("reason") or "error",
					"reason_description": entry.get("reason_description") or entry.get("error") or "",
				})
				continue

			files = entry.get("files")
			if isinstance(files, list) and files:
				for file in files:
					if not isinstance(file, dict):
						continue
					file_success = file.get("success", True)
					file_filename = file.get("filename")
					if not file_success:
						self.failures.append({
							"post_ids": post_ids,
							**({"url": url} if url is not None else {}),
							"reason": file.get("reason") or "error",
							"reason_description": file.get("reason_description") or file.get("error") or "",
						})
						continue
					if not file_filename:
						continue
					extra = dict(file.get("metadata") or {})
					self.items[file_filename] = self._build_item(
						file_filename, post_ids, url, extra
					)
			elif entry.get("filename"):
				filename = entry["filename"]
				self.items[filename] = self._build_item(
					filename, post_ids, url, dict(entry.get("extra") or {})
				)
			# else: malformed-but-tolerated; drop

	@staticmethod
	def _build_item(filename: str, post_ids: list, url, extra: dict) -> dict:
		item = {"filename": filename, "post_ids": list(post_ids)}
		if url is not None:
			item["url"] = url
		if extra:
			item["extra"] = extra
		return item

	# -- mutation --

	def add_item(self, filename: str, *, post_ids,
				 url: Optional[str] = None,
				 extra: Optional[dict] = None,
				 replace: bool = False) -> None:
		"""
		Record a successfully produced file.

		:param filename:  the file's name inside the archive. Must be unique
			within this metadata instance unless `replace=True`.
		:param post_ids:  list of source post IDs (string-coerced).
		:param url:  optional originating URL.
		:param extra:  optional free-form per-file data (e.g. yt-dlp dump).
		:param replace:  overwrite an existing entry with the same filename.
		"""
		if not filename or not isinstance(filename, str):
			raise MetadataException("add_item: 'filename' must be a non-empty string.")
		if not replace and filename in self.items:
			raise MetadataException(f"add_item: filename {filename!r} already present.")
		self.items[filename] = self._build_item(
			filename, self._normalize_post_ids(post_ids), url, dict(extra) if extra else {}
		)

	def add_failure(self, *, post_ids, reason: str,
					reason_description: Optional[str] = None,
					url: Optional[str] = None) -> None:
		"""
		Record a download attempt that did not produce a file.

		:param post_ids:  list of source post IDs (string-coerced; may be empty).
		:param reason:  structured failure code (e.g. "error", "no_media").
		:param reason_description:  optional human-readable explanation.
		:param url:  optional URL that was attempted.
		"""
		if not reason or not isinstance(reason, str):
			raise MetadataException("add_failure: 'reason' must be a non-empty string.")
		failure = {
			"post_ids": self._normalize_post_ids(post_ids),
			"reason": reason,
		}
		if url is not None:
			failure["url"] = url
		if reason_description is not None:
			failure["reason_description"] = reason_description
		self.failures.append(failure)

	@staticmethod
	def _normalize_post_ids(post_ids) -> list:
		if post_ids is None:
			return []
		if isinstance(post_ids, (str, int)):
			return [str(post_ids)]
		return [str(p) for p in post_ids]

	# -- access --

	def get_entry(self, filename: str) -> Optional[dict]:
		return self.items.get(filename)

	def iter_entries(self) -> Iterator[tuple]:
		return iter(self.items.items())

	def iter_failures(self) -> Iterator[dict]:
		return iter(self.failures)

	def filename_to_post_ids(self) -> dict:
		"""
		Return a `{filename: [post_id, ...]}` mapping for successful entries.

		Replaces the per-consumer map-building that strips extensions
		and walks nested `files[]` lists.
		"""
		return {fn: list(entry.get("post_ids", [])) for fn, entry in self.items.items()}

	def post_ids_for(self, filename: str) -> list:
		"""
		Return the list of source post IDs associated with a given filename, or
		empty list if the filename is not present or has no post IDs.
		"""
		entry = self.items.get(filename)
		return list(entry.get("post_ids", [])) if entry else []

	def entries_for_url(self, url: str) -> list:
		"""
		All items whose `url` field matches. Useful when a single source URL
		produced multiple output files (e.g. yt-dlp on a playlist).
		"""
		return [(fn, e) for fn, e in self.items.items() if e.get("url") == url]

	# -- some helpers for common access patterns --

	def __len__(self) -> int:
		return len(self.items)

	def __contains__(self, filename) -> bool:
		return filename in self.items

	# -- output --

	def to_dict(self) -> dict:
		return {
			"schema_version": self.schema_version,
			"from_dataset": self.from_dataset,
			"processor_type": self.processor_type,
			"software_version": self.software_version,
			"software_source": self.software_source,
			"items": self.items,
			"failures": self.failures,
		}

	def validate(self) -> None:
		"""
		Strict schema check used before writing. Raises MetadataException on
		any violation.
		"""
		if self.schema_version != self.SCHEMA_VERSION:
			raise MetadataException(f"Unsupported schema_version {self.schema_version}.")
		if not isinstance(self.items, dict):
			raise MetadataException("items must be a dict.")
		if not isinstance(self.failures, list):
			raise MetadataException("failures must be a list.")
		for filename, entry in self.items.items():
			if not isinstance(entry, dict):
				raise MetadataException(f"items[{filename!r}] must be a dict.")
			if entry.get("filename") != filename:
				raise MetadataException(
					f"items[{filename!r}].filename must match its key "
					f"(got {entry.get('filename')!r})."
				)
			if not isinstance(entry.get("post_ids"), list):
				raise MetadataException(f"items[{filename!r}].post_ids must be a list.")
		for i, failure in enumerate(self.failures):
			if not isinstance(failure, dict):
				raise MetadataException(f"failures[{i}] must be a dict.")
			if not isinstance(failure.get("post_ids"), list):
				raise MetadataException(f"failures[{i}].post_ids must be a list.")
			reason = failure.get("reason")
			if not isinstance(reason, str) or not reason:
				raise MetadataException(f"failures[{i}].reason must be a non-empty string.")
