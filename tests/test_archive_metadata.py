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

	def __init__(self, key, results_path, results_folder=None):
		self.key = key
		self._results = results_path
		self._results_folder = results_folder

	def check_dataset_finished(self):
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
	assert m.get_entry("vid1.mp4")["extra"] == {"title": "One", "view_count": 100}
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


def test_read_raises_when_dataset_unfinished():
	ds = FakeDataset("k", None)
	with pytest.raises(MetadataException, match="not finished"):
		MediaArchiveMetadata.read(ds)


def test_read_raises_when_dataset_empty():
	ds = FakeDataset("k", "empty")
	with pytest.raises(MetadataException, match="empty"):
		MediaArchiveMetadata.read(ds)


def test_read_raises_when_file_missing_from_zip(tmp_path):
	archive = tmp_path / "empty.zip"
	with zipfile.ZipFile(archive, "w") as zf:
		zf.writestr("README", "no metadata here")
	ds = FakeDataset("k", archive)
	with pytest.raises(FileNotFoundError):
		MediaArchiveMetadata.read(ds)
