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


# -- tracing a failure back to the run that recorded it --

class FakeDataset:
	"""A dataset stores the parameters it was created with; that is all that is needed here."""

	def __init__(self, key, parameters=None):
		self.key = key
		self.parameters = parameters or {}


def _meta_from(dataset):
	"""
	Metadata as read from a dataset.

	Uses the plain constructor rather than `new()`, which would try to resolve
	the 4CAT version from the dataset's processor.
	"""
	return MediaArchiveMetadata(dataset, processor_type="video-downloader", from_dataset="src")


def test_datasets_for_reason_returns_the_recording_dataset():
	dataset = FakeDataset("previous", {"also_indirect": "none"})
	m = _meta_from(dataset)
	m.add_failure(post_ids=["p1"], reason="not_a_video", url="https://example.com/x")
	lib = MediaArchiveLibrary([m])

	hit = lib.find("https://example.com/x")
	assert hit.datasets_for_reason("not_a_video") == [dataset]


def test_datasets_for_reason_ignores_other_reasons():
	"""
	Each reason has to be traced separately: a URL can fail one way in one run
	and another way in another, and the settings that produced each differ.
	"""
	errored = FakeDataset("errored", {"also_indirect": "all"})
	not_video = FakeDataset("not-video", {"also_indirect": "none"})
	m1 = _meta_from(errored)
	m1.add_failure(post_ids=["p1"], reason="error", url="https://example.com/x")
	m2 = _meta_from(not_video)
	m2.add_failure(post_ids=["p1"], reason="not_a_video", url="https://example.com/x")
	lib = MediaArchiveLibrary([m1, m2])

	hit = lib.find("https://example.com/x")
	assert hit.reasons == {"error", "not_a_video"}
	assert hit.datasets_for_reason("not_a_video") == [not_video]
	assert hit.datasets_for_reason("error") == [errored]


def test_datasets_for_reason_skips_metadata_without_a_dataset():
	"""Metadata built outside a dataset (e.g. in a test) has nothing to trace to."""
	m = _meta()
	m.add_failure(post_ids=["p1"], reason="not_a_video", url="https://example.com/x")
	lib = MediaArchiveLibrary([m])

	hit = lib.find("https://example.com/x")
	assert hit.reasons == {"not_a_video"}
	assert hit.datasets_for_reason("not_a_video") == []


# -- misc --

def test_items_without_url_are_not_indexed():
	"""Telegram-style entries have no URL; they must not crash indexing."""
	m = _meta()
	m.add_item("chat-1.mp4", post_ids=["chat-1"])  # no url
	lib = MediaArchiveLibrary([m])

	assert lib.find(None) is None
	assert len(lib) == 1


def test_find_through_other_url():
	"""A file reached through a second URL can be found through that URL too."""
	m = _meta()
	m.add_item("v.mp4", post_ids=["p1"], url="https://youtube.com/watch?v=abc")
	m.add_item("v.mp4", post_ids=["p2"], url="https://youtu.be/abc", merge=True)
	lib = MediaArchiveLibrary([m])

	hit = lib.find("https://youtu.be/abc")
	assert hit.is_success
	assert hit.metadata is m
	assert [fn for fn, _ in hit.entries] == ["v.mp4"]
	# its own URL still finds it, listed once
	assert [fn for fn, _ in lib.find("https://youtube.com/watch?v=abc").entries] == ["v.mp4"]


def test_find_failure_through_other_url():
	"""A failed download can also be found through each of its URLs."""
	m = _meta()
	m.add_failure(post_ids=["p1"], reason="not_a_video", url="https://example.com/page",
				  extra={"other_urls": ["http://example.com/page"]})
	lib = MediaArchiveLibrary([m])

	for url in ("https://example.com/page", "http://example.com/page"):
		hit = lib.find(url)
		assert not hit.is_success
		assert hit.reasons == {"not_a_video"}
		assert len(hit.failures) == 1


def test_other_urls_that_are_not_a_list_are_ignored():
	"""A hand-edited file may hold something else under `other_urls`."""
	m = _meta()
	m.add_item("v.mp4", post_ids=["p1"], url="https://example.com/v",
			   extra={"other_urls": "https://example.com/w"})
	lib = MediaArchiveLibrary([m])

	assert lib.find("https://example.com/v").is_success
	assert lib.find("https://example.com/w") is None


def test_len_reports_archive_count():
	lib = MediaArchiveLibrary([_meta(), _meta(), _meta()])
	assert len(lib) == 3


def test_success_prefers_the_archive_with_most_files():
	"""Runs allowed different numbers of videos per URL: use the one that got most."""
	m1 = _meta()
	m1.add_item("one_1.mp4", post_ids=["p1"], url="https://example.com/channel")
	m2 = _meta()
	m2.add_item("two_1.mp4", post_ids=["p1"], url="https://example.com/channel")
	m2.add_item("two_2.mp4", post_ids=["p1"], url="https://example.com/channel")
	lib = MediaArchiveLibrary([m1, m2])

	hit = lib.find("https://example.com/channel")
	assert hit.metadata is m2
	assert {fn for fn, _ in hit.entries} == {"two_1.mp4", "two_2.mp4"}
