"""
Tests for `common.lib.media_archive_library.MediaArchiveLibrary`.

Exercises `find()` resolution via the pure constructor (metadata objects
injected directly). The `collect()` path — walking parent/child datasets —
is left to integration/manual verification.
"""
from common.lib.archive_metadata import MediaArchiveMetadata
from common.lib.media_archive_library import MediaArchiveLibrary


def _meta():
	"""Build an empty MediaArchiveMetadata for tests to populate."""
	return MediaArchiveMetadata.new(processor_type="video-downloader", from_dataset="src")


# -- success lookups --

def test_find_success_returns_entry():
	m = _meta()
	m.add_item("v.mp4", post_ids=["p1"], url="https://example.com/v")
	lib = MediaArchiveLibrary([m])

	hit = lib.find("https://example.com/v")
	assert hit is not None
	assert hit.is_success
	assert hit.metadata is m
	assert hit.entries == [("v.mp4", m.get_entry("v.mp4"))]


def test_find_unknown_url_returns_none():
	m = _meta()
	m.add_item("v.mp4", post_ids=["p1"], url="https://example.com/v")
	lib = MediaArchiveLibrary([m])

	assert lib.find("https://example.com/never-seen") is None


def test_playlist_one_url_many_files():
	"""A single source URL that produced several files (yt-dlp playlist)."""
	m = _meta()
	m.add_item("v1.mp4", post_ids=["p1"], url="https://example.com/playlist")
	m.add_item("v2.mp4", post_ids=["p1"], url="https://example.com/playlist")
	lib = MediaArchiveLibrary([m])

	hit = lib.find("https://example.com/playlist")
	assert hit.is_success
	assert {fn for fn, _ in hit.entries} == {"v1.mp4", "v2.mp4"}


def test_success_groups_by_single_archive():
	"""URL downloaded by two archives: hit resolves to one archive's files."""
	m1 = _meta()
	m1.add_item("a.mp4", post_ids=["p1"], url="https://example.com/v")
	m2 = _meta()
	m2.add_item("b.mp4", post_ids=["p1"], url="https://example.com/v")
	lib = MediaArchiveLibrary([m1, m2])

	hit = lib.find("https://example.com/v")
	assert hit.is_success
	# all returned entries belong to the same (first) archive
	assert hit.metadata is m1
	assert {fn for fn, _ in hit.entries} == {"a.mp4"}


# -- failure lookups --

def test_find_failure_surfaces_reason():
	m = _meta()
	m.add_failure(post_ids=["p1"], reason="not_a_video", url="https://example.com/x")
	lib = MediaArchiveLibrary([m])

	hit = lib.find("https://example.com/x")
	assert hit is not None
	assert not hit.is_success
	assert hit.reasons == {"not_a_video"}


def test_failure_collects_all_reasons_across_archives():
	m1 = _meta()
	m1.add_failure(post_ids=["p1"], reason="error", url="https://example.com/x")
	m2 = _meta()
	m2.add_failure(post_ids=["p2"], reason="not_a_video", url="https://example.com/x")
	lib = MediaArchiveLibrary([m1, m2])

	hit = lib.find("https://example.com/x")
	assert not hit.is_success
	assert hit.reasons == {"error", "not_a_video"}


def test_success_beats_failure():
	"""URL downloaded in one archive, failed in another — success wins."""
	failed = _meta()
	failed.add_failure(post_ids=["p1"], reason="error", url="https://example.com/v")
	ok = _meta()
	ok.add_item("v.mp4", post_ids=["p1"], url="https://example.com/v")
	lib = MediaArchiveLibrary([failed, ok])

	hit = lib.find("https://example.com/v")
	assert hit.is_success
	assert hit.metadata is ok


# -- misc --

def test_items_without_url_are_not_indexed():
	"""Telegram-style entries have no URL; they must not crash indexing."""
	m = _meta()
	m.add_item("chat-1.mp4", post_ids=["chat-1"])  # no url
	lib = MediaArchiveLibrary([m])

	assert lib.find(None) is None
	assert len(lib) == 1


def test_len_reports_archive_count():
	lib = MediaArchiveLibrary([_meta(), _meta(), _meta()])
	assert len(lib) == 3
