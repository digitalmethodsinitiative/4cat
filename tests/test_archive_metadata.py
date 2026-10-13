"""
Tests for `common.lib.archive_metadata.MediaArchiveMetadata`.

Covers v1 round-trips, legacy format normalization (URL-keyed flat,
filename-keyed flat, video-style `files[]`, singular `post_id`), validation,
and the convenience helpers consumers rely on.
"""
import json
import zipfile

import pytest

from common.lib.archive_metadata import MediaArchiveMetadata
from common.lib.exceptions import MetadataException

CURRENT_SCHEMA_VERSION = MediaArchiveMetadata.SCHEMA_VERSION


class FakeDataset:
	"""Just enough surface for MediaArchiveMetadata.read."""

	def __init__(self, key, results_path, results_folder=None, finished=True):
		self.key = key
		self._results = results_path
		self._results_folder = results_folder
		self._finished = finished

	def is_finished(self):
		return self._finished

	def get_results_path(self):
		return self._results

	def get_results_folder_path(self):
		return self._results_folder

	def get_own_processor(self):
		return None


# -- v1 writer / reader round-trip --

def test_round_trip_minimal(tmp_path):
	meta = MediaArchiveMetadata.new(processor_type="image-downloader", from_dataset="src123")
	meta.add_item("a.jpg", post_ids=["p1", "p2"], url="https://example.com/a")
	meta.add_item("b.jpg", post_ids=["p3"])
	meta.add_failure(post_ids=["p4"], reason="error",
					 reason_description="boom", url="https://example.com/c")

	target = meta.write(tmp_path)
	assert target == tmp_path / ".metadata.json"

	raw = json.loads(target.read_text())
	assert raw["schema_version"] == 1
	assert raw["processor_type"] == "image-downloader"
	assert raw["from_dataset"] == "src123"
	assert set(raw["items"]) == {"a.jpg", "b.jpg"}
	assert raw["items"]["a.jpg"] == {
		"filename": "a.jpg",
		"post_ids": ["p1", "p2"],
		"url": "https://example.com/a",
	}
	assert raw["failures"] == [{
		"post_ids": ["p4"],
		"reason": "error",
		"url": "https://example.com/c",
		"reason_description": "boom",
	}]


def test_read_v1_from_zip(tmp_path):
	meta = MediaArchiveMetadata.new(processor_type="image-downloader", from_dataset="src")
	meta.add_item("a.jpg", post_ids=["1"], url="u")
	meta.write(tmp_path)

	archive = tmp_path / "results.zip"
	with zipfile.ZipFile(archive, "w") as zf:
		zf.write(tmp_path / ".metadata.json", ".metadata.json")

	loaded = MediaArchiveMetadata.read(FakeDataset("dskey", archive))
	assert loaded.schema_version == CURRENT_SCHEMA_VERSION
	assert loaded.processor_type == "image-downloader"
	assert loaded.from_dataset == "src"
	assert loaded.get_entry("a.jpg")["post_ids"] == ["1"]


def test_read_v1_from_folder(tmp_path):
	meta = MediaArchiveMetadata.new(processor_type="image-downloader", from_dataset="src")
	meta.add_item("a.jpg", post_ids=["1"])
	folder = tmp_path / "folder_dskey"
	folder.mkdir()
	meta.write(folder)

	ds = FakeDataset("dskey", tmp_path / "results.csv", results_folder=folder)
	loaded = MediaArchiveMetadata.read(ds)
	assert "a.jpg" in loaded
	assert len(loaded) == 1


# -- legacy normalization --

def test_legacy_url_keyed_flat(tmp_path):
	"""Image-downloader style: URL keys, flat filenames, success bool."""
	legacy = {
		"https://example.com/a.jpg": {
			"filename": "a.jpg",
			"success": True,
			"from_dataset": "src",
			"post_ids": ["p1", "p2"],
			"url": "https://example.com/a.jpg",
		},
		"https://example.com/b.jpg": {
			"filename": "b.jpg",
			"success": False,
			"from_dataset": "src",
			"post_ids": ["p3"],
		},
	}
	path = tmp_path / ".metadata.json"
	path.write_text(json.dumps(legacy))

	# Easiest to invoke `_populate_from_raw` directly rather than building a
	# fake on-disk archive.
	m = MediaArchiveMetadata()
	m._populate_from_raw(legacy)

	assert m.from_dataset == "src"
	assert m.get_entry("a.jpg")["post_ids"] == ["p1", "p2"]
	assert m.get_entry("a.jpg")["url"] == "https://example.com/a.jpg"
	assert "b.jpg" not in m
	assert len(m.failures) == 1
	assert m.failures[0]["post_ids"] == ["p3"]
	assert m.failures[0]["url"] == "https://example.com/b.jpg"
	assert m.failures[0]["reason"] == "error"


def test_legacy_video_files_array(tmp_path):
	"""Video-downloader style: URL keys, nested files[] with per-file metadata."""
	legacy = {
		"https://example.com/playlist": {
			"success": True,
			"from_dataset": "src",
			"post_ids": ["p1"],
			"downloader": "yt_dlp",
			"files": [
				{"filename": "vid1.mp4", "success": True,
				 "metadata": {"title": "One", "view_count": 100}},
				{"filename": "vid2.mp4", "success": True,
				 "metadata": {"title": "Two"}},
			],
		},
		"https://example.com/dead": {
			"success": False,
			"from_dataset": "src",
			"post_ids": ["p2"],
			"error": "404 Not Found",
		},
	}
	m = MediaArchiveMetadata()
	m._populate_from_raw(legacy)

	assert set(m.items) == {"vid1.mp4", "vid2.mp4"}
	assert m.get_entry("vid1.mp4")["url"] == "https://example.com/playlist"
	assert m.get_entry("vid1.mp4")["post_ids"] == ["p1"]
	# per-file yt-dlp metadata is flattened in, and the outer-level
	# `downloader` is carried onto every file so nothing is lost
	assert m.get_entry("vid1.mp4")["extra"] == {
		"downloader": "yt_dlp", "title": "One", "view_count": 100,
	}
	assert m.get_entry("vid2.mp4")["extra"] == {
		"downloader": "yt_dlp", "title": "Two",
	}
	assert m.get_entry("vid2.mp4")["post_ids"] == ["p1"]

	# url is shared across the playlist's outputs
	assert m.get_entry("vid2.mp4")["url"] == "https://example.com/playlist"

	# failure preserved with description from `error`
	assert len(m.failures) == 1
	assert m.failures[0]["url"] == "https://example.com/dead"
	assert m.failures[0]["reason_description"] == "404 Not Found"


def test_legacy_telegram_filename_keyed():
	"""Telegram style: filename keys, structured reason codes."""
	legacy = {
		"chat-100.mp4": {
			"filename": "chat-100.mp4", "success": True,
			"from_dataset": "src", "post_ids": ["chat-100"],
			"reason": "ok", "reason_description": "downloaded",
		},
		"chat-101.mp4": {
			"filename": "chat-101.mp4", "success": False,
			"from_dataset": "src", "post_ids": ["chat-101"],
			"reason": "restricted_channel",
			"reason_description": "Telegram refused: channel restrictions.",
		},
	}
	m = MediaArchiveMetadata()
	m._populate_from_raw(legacy)

	assert "chat-100.mp4" in m
	assert "chat-101.mp4" not in m
	assert m.failures[0]["reason"] == "restricted_channel"
	assert m.failures[0]["post_ids"] == ["chat-101"]
	# no URL stored for telegram entries
	assert "url" not in m.failures[0]


def test_legacy_not_a_video_keeps_its_reason():
	"""The old video downloader marked URLs that were not videos with `retry: False`."""
	legacy = {
		"https://example.com/page": {
			"success": False, "retry": False, "also_indirect": "none",
			"post_ids": ["p1"], "error": "Not a video",
		},
	}
	m = MediaArchiveMetadata()
	m._populate_from_raw(legacy)
	assert m.failures[0]["reason"] == "not_a_video"
	assert m.failures[0]["reason_description"] == "Not a video"


def test_legacy_singular_post_id():
	legacy = {
		"https://example.com/a.jpg": {
			"filename": "a.jpg", "success": True, "post_id": "p1",
		},
	}
	m = MediaArchiveMetadata()
	m._populate_from_raw(legacy)
	assert m.get_entry("a.jpg")["post_ids"] == ["p1"]


def test_legacy_unsupported_schema_version_raises():
	with pytest.raises(MetadataException, match="Unsupported"):
		m = MediaArchiveMetadata()
		m._populate_from_raw({"schema_version": 99, "items": {}})


def test_legacy_single_file_preserves_top_level_extra():
	"""Pre-v1 files kept producer data (e.g. the SD prompt) at the top level."""
	legacy = {
		"p1": {
			"filename": "p1-cat.jpeg", "success": True, "post_ids": ["p1"],
			"from_dataset": "src",
			"prompt": "a cat", "negative-prompt": "a dog",
		},
	}
	m = MediaArchiveMetadata()
	m._populate_from_raw(legacy)
	assert m.get_entry("p1-cat.jpeg")["extra"] == {
		"prompt": "a cat", "negative-prompt": "a dog",
	}


def test_legacy_failure_preserves_extra():
	"""Producer data on a failed legacy entry survives under failure['extra']."""
	legacy = {
		"https://example.com/playlist": {
			"success": True, "from_dataset": "src", "post_ids": ["p1"],
			"downloader": "yt_dlp",
			"files": [
				{"filename": "good.mp4", "success": True, "metadata": {"title": "ok"}},
				{"filename": "", "success": False, "error": "geo-blocked",
				 "region": "NL"},
			],
		},
	}
	m = MediaArchiveMetadata()
	m._populate_from_raw(legacy)

	assert len(m.failures) == 1
	failure = m.failures[0]
	assert failure["reason_description"] == "geo-blocked"
	# the outer `downloader` and the per-file `region` are both kept; the
	# promoted reason/error keys are not duplicated into extra
	assert failure["extra"] == {"downloader": "yt_dlp", "region": "NL"}


# -- helper API --

def test_filename_to_post_ids():
	m = MediaArchiveMetadata.new(processor_type="x", from_dataset="y")
	m.add_item("a.jpg", post_ids=["1", "2"])
	m.add_item("b.jpg", post_ids=["3"])
	assert m.filename_to_post_ids() == {"a.jpg": ["1", "2"], "b.jpg": ["3"]}


def test_post_ids_for():
	m = MediaArchiveMetadata.new(processor_type="x", from_dataset="y")
	m.add_item("a.jpg", post_ids=["1"])
	assert m.post_ids_for("a.jpg") == ["1"]
	assert m.post_ids_for("missing.jpg") == []


def test_add_item_normalizes_post_ids():
	m = MediaArchiveMetadata.new(processor_type="x", from_dataset="y")
	m.add_item("a.jpg", post_ids="p1")          # bare string
	m.add_item("b.jpg", post_ids=42)            # bare int
	m.add_item("c.jpg", post_ids=[1, 2, 3])     # ints in list
	assert m.get_entry("a.jpg")["post_ids"] == ["p1"]
	assert m.get_entry("b.jpg")["post_ids"] == ["42"]
	assert m.get_entry("c.jpg")["post_ids"] == ["1", "2", "3"]


def test_add_item_drops_null_and_blank_post_ids():
	"""
	Media with no traceable item (e.g. Instagram ads) records a null or blank
	post id. These are dropped, not kept as the text "None" or "", so nothing
	downstream tries to match on a fabricated id.
	"""
	m = MediaArchiveMetadata.new(processor_type="x", from_dataset="y")
	m.add_item("a.jpg", post_ids=[None])
	m.add_item("b.jpg", post_ids=[None, "p1", "  ", "p2"])
	m.add_item("c.jpg", post_ids=[])
	assert m.get_entry("a.jpg")["post_ids"] == []
	assert m.get_entry("b.jpg")["post_ids"] == ["p1", "p2"]
	assert m.get_entry("c.jpg")["post_ids"] == []


def test_legacy_null_post_ids_dropped():
	"""The old image downloader wrote `post_ids: [null]` for ad media."""
	legacy = {
		"https://example.com/ad.jpg": {
			"filename": "ad.jpg",
			"success": True,
			"from_dataset": "src",
			"post_ids": [None],
		},
	}
	m = MediaArchiveMetadata()
	m._populate_from_raw(legacy)
	# the file is still recorded, it just has no item to trace back to
	assert m.get_entry("ad.jpg")["post_ids"] == []


def test_add_item_duplicate_raises():
	m = MediaArchiveMetadata.new(processor_type="x", from_dataset="y")
	m.add_item("a.jpg", post_ids=["1"])
	with pytest.raises(MetadataException, match="already present"):
		m.add_item("a.jpg", post_ids=["2"])


def test_add_item_replace_overwrites():
	m = MediaArchiveMetadata.new(processor_type="x", from_dataset="y")
	m.add_item("a.jpg", post_ids=["1"])
	m.add_item("a.jpg", post_ids=["2"], replace=True)
	assert m.post_ids_for("a.jpg") == ["2"]


def test_add_item_merge_keeps_posts_of_every_url():
	"""One file reached through two URLs stays connected to the posts of both."""
	m = MediaArchiveMetadata.new(processor_type="x", from_dataset="y")
	m.add_item("v.mp4", post_ids=["1", "2"], url="https://a.example/v",
			   extra={"title": "first"})
	m.add_item("v.mp4", post_ids=["2", "3"], url="https://b.example/v",
			   extra={"title": "second", "downloader": "yt_dlp"}, merge=True)

	entry = m.get_entry("v.mp4")
	assert entry["post_ids"] == ["1", "2", "3"]
	# the first URL and the data recorded with it are kept; only new keys are
	# added, and the second URL is listed as another way to reach the file
	assert entry["url"] == "https://a.example/v"
	assert entry["extra"] == {
		"title": "first", "downloader": "yt_dlp",
		"other_urls": ["https://b.example/v"],
	}


def test_add_item_merge_lists_each_other_url_once():
	m = MediaArchiveMetadata.new(processor_type="x", from_dataset="y")
	m.add_item("v.mp4", post_ids=["1"], url="https://a.example/v")
	m.add_item("v.mp4", post_ids=["2"], url="https://b.example/v", merge=True)
	m.add_item("v.mp4", post_ids=["3"], url="https://b.example/v", merge=True)
	m.add_item("v.mp4", post_ids=["4"], url="https://c.example/v", merge=True)
	# the same URL as the entry's own, or no URL at all, adds nothing
	m.add_item("v.mp4", post_ids=["5"], url="https://a.example/v", merge=True)
	m.add_item("v.mp4", post_ids=["6"], merge=True)

	entry = m.get_entry("v.mp4")
	assert entry["post_ids"] == ["1", "2", "3", "4", "5", "6"]
	assert entry["extra"]["other_urls"] == ["https://b.example/v", "https://c.example/v"]


def test_add_item_merge_fills_in_missing_url():
	"""A file first recorded without a URL takes the next URL as its own."""
	m = MediaArchiveMetadata.new(processor_type="x", from_dataset="y")
	m.add_item("v.mp4", post_ids=["1"])
	m.add_item("v.mp4", post_ids=["2"], url="https://a.example/v", merge=True)
	entry = m.get_entry("v.mp4")
	assert entry["url"] == "https://a.example/v"
	assert "extra" not in entry


def test_add_item_merge_adds_new_file():
	m = MediaArchiveMetadata.new(processor_type="x", from_dataset="y")
	m.add_item("v.mp4", post_ids=["1"], merge=True)
	assert m.post_ids_for("v.mp4") == ["1"]


def test_add_item_merge_and_replace_together_raises():
	m = MediaArchiveMetadata.new(processor_type="x", from_dataset="y")
	with pytest.raises(MetadataException, match="either"):
		m.add_item("v.mp4", post_ids=["1"], replace=True, merge=True)


def test_legacy_file_shared_by_two_urls_keeps_all_post_ids():
	"""
	The old video downloader could list one file under two URLs, when yt-dlp
	recognised a video it had already downloaded for an earlier URL. The second
	URL was then marked unsuccessful, but still listed the file.
	"""
	legacy = {
		"https://youtube.com/watch?v=abc": {
			"success": True, "post_ids": ["p1"], "downloader": "yt_dlp",
			"files": [{"filename": "abc.mp4", "success": True, "metadata": {"id": "abc"}}],
		},
		"https://youtu.be/abc": {
			"success": False, "post_ids": ["p2"], "downloader": "yt_dlp",
			"files": [{"filename": "abc.mp4", "success": True, "metadata": {"id": "abc"}}],
		},
	}
	m = MediaArchiveMetadata()
	m._populate_from_raw(legacy)

	assert m.post_ids_for("abc.mp4") == ["p1", "p2"]
	assert m.get_entry("abc.mp4")["url"] == "https://youtube.com/watch?v=abc"
	assert m.get_entry("abc.mp4")["extra"]["other_urls"] == ["https://youtu.be/abc"]
	# the second URL did produce a file, so it is not also a failure
	assert m.failures == []


def test_legacy_unsuccessful_url_without_files_is_a_failure():
	legacy = {
		"https://example.com/gone": {
			"success": False, "post_ids": ["p1"], "error": "404", "files": [],
		},
	}
	m = MediaArchiveMetadata()
	m._populate_from_raw(legacy)
	assert len(m) == 0
	assert m.failures[0]["post_ids"] == ["p1"]
	assert m.failures[0]["reason_description"] == "404"


# -- validation --

def test_validate_rejects_filename_mismatch(tmp_path):
	m = MediaArchiveMetadata.new(processor_type="x", from_dataset="y")
	m.items["a.jpg"] = {"filename": "b.jpg", "post_ids": []}
	with pytest.raises(MetadataException, match="must match its key"):
		m.validate()


def test_validate_rejects_non_list_post_ids():
	m = MediaArchiveMetadata.new(processor_type="x", from_dataset="y")
	m.items["a.jpg"] = {"filename": "a.jpg", "post_ids": "p1"}
	with pytest.raises(MetadataException, match="post_ids must be a list"):
		m.validate()


def test_validate_rejects_failure_without_reason():
	m = MediaArchiveMetadata.new(processor_type="x", from_dataset="y")
	m.failures.append({"post_ids": [], "reason": ""})
	with pytest.raises(MetadataException, match="reason"):
		m.validate()


def test_read_raises_when_dataset_unfinished(tmp_path):
	ds = FakeDataset("k", tmp_path / "results.zip", finished=False)
	with pytest.raises(MetadataException, match="not finished"):
		MediaArchiveMetadata.read(ds)


def test_read_finished_dataset_without_items(tmp_path):
	"""
	An archive in which every download failed (or every file was copied from an
	earlier download) finishes with no items, but its metadata is still read.
	"""
	meta = MediaArchiveMetadata.new(processor_type="video-downloader", from_dataset="src")
	meta.add_failure(post_ids=["1"], reason="not_a_video", url="https://example.com/page")
	meta.write(tmp_path)
	archive = tmp_path / "results.zip"
	with zipfile.ZipFile(archive, "w") as zf:
		zf.write(tmp_path / ".metadata.json", ".metadata.json")

	loaded = MediaArchiveMetadata.read(FakeDataset("k", archive))
	assert loaded.failures[0]["reason"] == "not_a_video"


def test_read_raises_when_finished_dataset_has_no_archive(tmp_path):
	ds = FakeDataset("k", tmp_path / "results.zip")
	with pytest.raises(FileNotFoundError):
		MediaArchiveMetadata.read(ds)


def test_read_raises_when_file_missing_from_zip(tmp_path):
	archive = tmp_path / "empty.zip"
	with zipfile.ZipFile(archive, "w") as zf:
		zf.writestr("README", "no metadata here")
	ds = FakeDataset("k", archive)
	with pytest.raises(FileNotFoundError):
		MediaArchiveMetadata.read(ds)


def test_read_raises_metadata_exception_on_malformed_json(tmp_path):
	"""A corrupt metadata file surfaces as MetadataException, not JSONDecodeError."""
	archive = tmp_path / "bad.zip"
	with zipfile.ZipFile(archive, "w") as zf:
		zf.writestr(".metadata.json", "{ not valid json ]")
	ds = FakeDataset("k", archive)
	with pytest.raises(MetadataException, match="not valid JSON"):
		MediaArchiveMetadata.read(ds)


def test_read_raises_metadata_exception_on_damaged_zip(tmp_path):
	archive = tmp_path / "results.zip"
	archive.write_bytes(b"this is not a zip file")
	with pytest.raises(MetadataException, match="cannot be opened"):
		MediaArchiveMetadata.read(FakeDataset("k", archive))


def test_read_raises_metadata_exception_on_text_that_is_not_utf8(tmp_path):
	folder = tmp_path / "folder_k"
	folder.mkdir()
	(folder / ".metadata.json").write_bytes(b'{"items": "\xff\xfe"}')
	ds = FakeDataset("k", tmp_path / "results.csv", results_folder=folder)
	with pytest.raises(MetadataException, match="not valid JSON"):
		MediaArchiveMetadata.read(ds)


def test_v1_read_rejects_items_that_are_not_an_object():
	m = MediaArchiveMetadata()
	with pytest.raises(MetadataException, match="items"):
		m._populate_from_raw({"schema_version": 1, "items": ["a.jpg"]})


def test_v1_read_tolerates_empty_and_malformed_entries():
	"""Missing or null lists count as empty; entries that are not objects are skipped."""
	m = MediaArchiveMetadata()
	m._populate_from_raw({"schema_version": 1, "items": None, "failures": None})
	assert len(m) == 0
	assert m.failures == []

	m = MediaArchiveMetadata()
	m._populate_from_raw({
		"schema_version": 1,
		"items": {"a.jpg": {"filename": "a.jpg", "post_ids": ["1"]}, "b.jpg": "oops"},
		"failures": [{"post_ids": ["2"], "reason": "error"}, "oops"],
	})
	assert list(m.items) == ["a.jpg"]
	assert len(m.failures) == 1


def test_legacy_source_dataset_key_is_read_as_from_dataset():
	"""Video downloads from early 2023 recorded the source as `source_dataset`."""
	legacy = {
		"https://example.com/v": {
			"success": True, "source_dataset": "src", "post_ids": ["p1"],
			"files": [{"filename": "v.mp4", "success": True}],
		},
	}
	m = MediaArchiveMetadata()
	m._populate_from_raw(legacy)
	assert m.from_dataset == "src"
	assert "source_dataset" not in m.get_entry("v.mp4").get("extra", {})


def test_v1_read_normalizes_integer_post_ids():
	"""Integer post_ids in a v1 file are coerced to strings on read."""
	raw = {
		"schema_version": 1,
		"items": {"a.jpg": {"filename": "a.jpg", "post_ids": [1, 2]}},
		"failures": [{"post_ids": [3], "reason": "error"}],
	}
	m = MediaArchiveMetadata()
	m._populate_from_raw(raw)
	assert m.get_entry("a.jpg")["post_ids"] == ["1", "2"]
	assert m.failures[0]["post_ids"] == ["3"]
