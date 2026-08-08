"""
Tests for the metadata viewer processor.

The processor reads a media archive's metadata and, where it can find the dataset
the media was downloaded from, adds that dataset's columns to each row. These
tests cover that join: which dataset is picked, how a media file used by several
items is written out, and what happens to media that cannot be traced back.

Also covers the `_from_dataset` override that lets a preset tell the video
downloader which dataset to credit, instead of the helper dataset it built.

The processors are built with `__new__` and given stand-ins for the few
attributes they use, so none of the worker machinery (database, job queue,
config) has to be started up.
"""
import csv
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from common.lib.archive_metadata import MediaArchiveMetadata
# imported as a module as well so that `DataSet` and `DataSetException` can be
# reached exactly as the processor sees them; another test module replaces some
# `common.lib` entries in sys.modules, so importing them again here is not safe
from processors.conversion import view_metadata
from processors.conversion.view_metadata import ViewMetadata


class FakeProducer:
    """Stands in for the downloader that made the archive."""
    type = "image-downloader"

    @classmethod
    def map_metadata(cls, filename, item):
        yield {
            "url": item.get("url", ""),
            "filename": filename,
            "post_ids": ", ".join(item.get("post_ids", [])),
            "download_successful": True,
        }

    @classmethod
    def map_failure_metadata(cls, failure):
        yield {
            "url": failure.get("url", ""),
            "filename": "",
            "post_ids": ", ".join(failure.get("post_ids", [])),
            "download_successful": False,
        }


class FakeDataset:
    """Records what the processor reports, so tests can assert on it."""

    def __init__(self, results_path=None, key="fake", num_rows=0,
                 dataset_type="image-downloader", columns=None, items=None,
                 metadata=None):
        self.key = key
        self.type = dataset_type
        self.num_rows = num_rows
        self._results_path = results_path
        self._columns = columns or []
        self._items = items or []
        self._metadata = metadata
        self.logs = []
        self.statuses = []
        self.finished = None
        self.warning = None
        self.error = None
        self.parent = None

    # -- used when this dataset is the processor's own output --

    def get_results_path(self):
        return self._results_path

    def log(self, message):
        self.logs.append(message)

    def update_status(self, message, is_final=False):
        self.statuses.append(message)

    def finish(self, num_rows=0):
        self.finished = num_rows

    def finish_with_warning(self, num_rows, warning):
        self.finished = num_rows
        self.warning = warning

    def finish_with_error(self, error):
        self.error = error

    # -- used when this dataset is the archive being read --

    def read_media_metadata(self, filename=".metadata.json"):
        if self._metadata is None:
            raise FileNotFoundError("no metadata")
        return self._metadata

    def get_own_processor(self):
        return FakeProducer

    # -- used when this dataset is a source of items --

    def get_columns(self):
        return list(self._columns)

    def get_label(self):
        return f"dataset {self.key}"

    def get_parent(self):
        return self.parent

    def is_finished(self):
        return True

    def iterate_items(self, processor=None, **kwargs):
        for item in self._items:
            yield dict(item)


def make_metadata(from_dataset="posts", items=(), failures=()):
    """
    Build real archive metadata, so the tests go through the same normalising
    the processor relies on.

    :param str from_dataset:  key the archive records as its source
    :param items:  (filename, post_ids, url) tuples
    :param failures:  (post_ids, reason) tuples
    """
    metadata = MediaArchiveMetadata(from_dataset=from_dataset)
    for filename, post_ids, url in items:
        metadata.add_item(filename, post_ids=post_ids, url=url)
    for post_ids, reason in failures:
        metadata.add_failure(post_ids=post_ids, reason=reason)
    return metadata


def make_processor(tmp_path, metadata=None, parameters=None, source_dataset=None):
    """
    Build a ViewMetadata with stand-ins for everything it reads.

    :param tmp_path:  pytest temporary directory
    :param metadata:  archive metadata, as built by `make_metadata`
    :param dict parameters:  processor parameters
    :param source_dataset:  dataset the media came from; when given, the search
      for it is replaced by this, since that search is covered on its own
    :return tuple:  the processor and its output dataset
    """
    output = FakeDataset(results_path=tmp_path.joinpath("result.csv"))

    processor = ViewMetadata.__new__(ViewMetadata)
    processor.dataset = output
    processor.source_dataset = FakeDataset(dataset_type="image-downloader", key="archive",
                                          metadata=metadata)
    processor.parameters = parameters if parameters is not None else {}
    processor.interrupted = False
    processor.log = MagicMock()
    if source_dataset is not None:
        processor.find_origin_datasets = lambda _: [(source_dataset, "test")]

    return processor, output


def read_result(output):
    with output.get_results_path().open(encoding="utf-8", newline="") as infile:
        reader = csv.DictReader(infile)
        return reader.fieldnames, list(reader)


# -- item IDs --

@pytest.mark.parametrize("item,expected", [
    ({"id": "p1"}, ["p1"]),
    ({"id": 12}, ["12"]),  # some datasources number their items
    ({"id": " p1 "}, ["p1"]),
    ({}, [""]),
    ({"ids": "1,2,3"}, ["1", "2", "3"]),  # rows that combine several items
    ({"ids": "1, 2", "id": "ignored"}, ["1", "2"]),
])
def test_item_ids(item, expected):
    assert ViewMetadata.item_ids(item) == expected


# -- recognising media archives --

@pytest.mark.parametrize("dataset_type,expected", [
    ("image-downloader", True),
    ("image-downloader-unique", True),  # a filtered image archive
    ("video-downloader-telegram", True),
    ("video-downloader-tiktok", True),  # the preset, which carries its own type
    ("tiktok-search", False),
    ("metadata-viewer", False),
])
def test_is_media_archive(dataset_type, expected):
    module = SimpleNamespace(type=dataset_type)
    assert ViewMetadata.is_media_archive(module) is expected
    assert ViewMetadata.is_compatible_with(module) is expected


# -- reading the metadata --

def test_collect_media_rows_prefixes_and_dedupes(tmp_path):
    metadata = make_metadata(items=[
        ("1.jpg", ["p1", "p2"], "http://example.com/1.jpg"),
        ("2.jpg", [3, 3, " 4 "], "http://example.com/2.jpg"),
    ])
    processor, _ = make_processor(tmp_path, metadata)

    rows, wanted_ids = processor.collect_media_rows(metadata, FakeProducer)

    assert len(rows) == 2
    # every column read from the metadata is prefixed, so it cannot collide with
    # a column of the dataset the media came from
    assert set(rows[0][0]) == {"media_url", "media_filename", "media_post_ids",
                               "media_download_successful"}
    assert rows[0][1] == ["p1", "p2"]
    # numbers become text, whitespace is trimmed and duplicates are dropped
    assert rows[1][1] == ["3", "4"]
    assert wanted_ids == {"p1", "p2", "3", "4"}


def test_collect_media_rows_skips_failures_unless_asked(tmp_path):
    metadata = make_metadata(items=[("1.jpg", ["p1"], None)],
                             failures=[(["p2"], "error")])
    processor, _ = make_processor(tmp_path, metadata)

    rows, wanted_ids = processor.collect_media_rows(metadata, FakeProducer)
    assert [row["media_filename"] for row, _ in rows] == ["1.jpg"]
    assert wanted_ids == {"p1"}

    processor.parameters = {"include_failed": True}
    rows, wanted_ids = processor.collect_media_rows(metadata, FakeProducer)
    assert [row["media_filename"] for row, _ in rows] == ["1.jpg", ""]
    # a download that produced no file still records what it was for, so the
    # failure can be traced back to an item too
    assert rows[1][1] == ["p2"]
    assert wanted_ids == {"p1", "p2"}


# -- working out the columns --

def test_build_fieldnames_unions_rows_and_appends_source_columns(tmp_path):
    processor, _ = make_processor(tmp_path)
    media_rows = [
        ({"media_url": "a", "media_filename": "1.jpg"}, []),
        ({"media_url": "b", "media_error": "timed out"}, []),  # a column only some rows have
    ]

    fieldnames, source_map = processor.build_fieldnames(media_rows, ["id", "body"])

    assert fieldnames == ["media_url", "media_filename", "media_error",
                          "media_source_matched", "id", "body"]
    assert source_map == {"id": "id", "body": "body"}


def test_build_fieldnames_without_source_dataset(tmp_path):
    processor, _ = make_processor(tmp_path)
    fieldnames, source_map = processor.build_fieldnames([({"media_url": "a"}, [])], [])

    # nothing to combine with, so no column saying whether a row was traced back
    assert fieldnames == ["media_url"]
    assert source_map == {}


def test_build_fieldnames_renames_clashing_source_column(tmp_path):
    processor, _ = make_processor(tmp_path)
    media_rows = [({"media_url": "a", "media_filename": "1.jpg"}, [])]

    fieldnames, source_map = processor.build_fieldnames(media_rows, ["id", "media_filename"])

    assert fieldnames == ["media_url", "media_filename", "media_source_matched", "id",
                          "source_media_filename"]
    # the renamed column must still be filled from the original column name
    assert source_map == {"id": "id", "media_filename": "source_media_filename"}


# -- finding the dataset the media came from --

def test_find_origin_datasets_orders_recorded_first(tmp_path, monkeypatch):
    metadata = make_metadata(from_dataset="recorded")
    processor, _ = make_processor(tmp_path, metadata)
    processor.db = MagicMock()
    processor.modules = MagicMock()

    recorded = FakeDataset(key="recorded", num_rows=5, dataset_type="tiktok-search")
    posts = FakeDataset(key="posts", num_rows=10, dataset_type="tiktok-search")
    processor.source_dataset.parent = posts

    monkeypatch.setattr(view_metadata, "DataSet", lambda **kwargs: recorded)
    candidates = processor.find_origin_datasets(metadata)

    assert [(dataset.key, how) for dataset, how in candidates] == [
        ("recorded", "recorded in the metadata file"),
        ("posts", "found by walking up the chain of parent datasets"),
    ]


def test_find_origin_datasets_walks_past_media_archives(tmp_path, monkeypatch):
    """A deleted source dataset leaves only the chain of parent datasets."""
    metadata = make_metadata(from_dataset="deleted")
    processor, _ = make_processor(tmp_path, metadata)
    processor.db = MagicMock()
    processor.modules = MagicMock()

    posts = FakeDataset(key="posts", num_rows=10, dataset_type="tiktok-search")
    # the archive was made from another archive, e.g. by filtering duplicates
    intermediate = FakeDataset(key="unique", num_rows=4, dataset_type="image-downloader-unique")
    intermediate.parent = posts
    processor.source_dataset.parent = intermediate

    def raise_missing(**kwargs):
        raise view_metadata.DataSetException("gone")

    monkeypatch.setattr(view_metadata, "DataSet", raise_missing)
    candidates = processor.find_origin_datasets(metadata)

    assert [dataset.key for dataset, _ in candidates] == ["posts"]


def test_find_origin_datasets_does_not_repeat_one_dataset(tmp_path, monkeypatch):
    metadata = make_metadata(from_dataset="posts")
    processor, _ = make_processor(tmp_path, metadata)
    processor.db = MagicMock()
    processor.modules = MagicMock()

    posts = FakeDataset(key="posts", num_rows=10, dataset_type="tiktok-search")
    processor.source_dataset.parent = posts

    monkeypatch.setattr(view_metadata, "DataSet", lambda **kwargs: posts)
    assert len(processor.find_origin_datasets(metadata)) == 1


def test_collect_source_data_falls_back_when_recorded_dataset_has_no_items(tmp_path):
    """
    The recorded dataset can be a helper a preset built, whose items are not the
    ones the media refers to. When it accounts for nothing, the next candidate is
    tried rather than reporting an empty join.
    """
    processor, output = make_processor(tmp_path)
    helper = FakeDataset(key="helper", num_rows=1, columns=["id", "video_url"],
                         items=[{"id": "unrelated", "video_url": "http://a"}])
    posts = FakeDataset(key="posts", num_rows=1, columns=["id", "body"],
                        items=[{"id": "p1", "body": "first"}])
    processor.find_origin_datasets = lambda _: [(helper, "recorded in the metadata file"),
                                                (posts, "found by walking up")]

    columns, items = processor.collect_source_data(None, {"p1"})

    assert columns == ["id", "body"]
    assert items == {"p1": {"id": "p1", "body": "first"}}
    assert any("has none of the items" in message for message in output.logs)


def test_collect_source_data_keeps_columns_when_nothing_matches(tmp_path):
    """
    If no candidate accounts for any media, the best guess is still used so the
    result carries its columns and the mismatch gets reported.
    """
    processor, _ = make_processor(tmp_path)
    helper = FakeDataset(key="helper", num_rows=1, columns=["id", "video_url"],
                         items=[{"id": "unrelated", "video_url": "http://a"}])
    processor.find_origin_datasets = lambda _: [(helper, "recorded in the metadata file")]

    columns, items = processor.collect_source_data(None, {"p1"})

    assert columns == ["id", "video_url"]
    assert items == {}


def test_collect_source_data_skips_unreadable_dataset(tmp_path):
    processor, output = make_processor(tmp_path)
    archive = FakeDataset(key="zip", num_rows=3, columns=[])  # no readable columns
    processor.find_origin_datasets = lambda _: [(archive, "recorded in the metadata file")]

    assert processor.collect_source_data(None, {"p1"}) == ([], {})
    assert any("no readable columns" in message for message in output.logs)


def test_collect_source_items_reports_unmappable_source_items(tmp_path):
    """
    A dataset can have more rows than it yields when some items cannot be mapped
    (e.g. Instagram ads). If that leaves media untraced, the gap is reported so
    a partial join is not mistaken for missing metadata.
    """
    processor, output = make_processor(tmp_path)
    # 5 rows, but only 3 items come back from iteration: 2 were unmappable
    dataset = FakeDataset(key="posts", num_rows=5, columns=["id", "body"],
                          items=[{"id": "p1", "body": "a"}, {"id": "p2", "body": "b"},
                                 {"id": "p3", "body": "c"}])

    found = processor.collect_source_items(dataset, ["id", "body"], {"p1", "p2", "gone"})

    assert set(found) == {"p1", "p2"}
    assert any("could not be read" in message and "2 of 5" in message for message in output.logs)


def test_collect_source_items_silent_when_all_media_traced(tmp_path):
    """No report when every item the media refers to was found, even if the
    dataset also holds unrelated rows that were never reached."""
    processor, output = make_processor(tmp_path)
    dataset = FakeDataset(key="posts", num_rows=9, columns=["id", "body"],
                          items=[{"id": "p1", "body": "a"}, {"id": "p2", "body": "b"}])

    found = processor.collect_source_items(dataset, ["id", "body"], {"p1", "p2"})

    assert set(found) == {"p1", "p2"}
    assert not any("could not be read" in message for message in output.logs)


# -- the whole thing --

def test_process_joins_source_dataset(tmp_path):
    """
    A media file used by two items becomes two rows; one that cannot be traced
    back to an item keeps its row with the source columns empty.
    """
    metadata = make_metadata(items=[
        ("1.jpg", ["p1", "p2"], "http://example.com/1.jpg"),
        ("2.jpg", [3], "http://example.com/2.jpg"),
        ("4.jpg", ["gone"], "http://example.com/4.jpg"),
    ])
    source = FakeDataset(key="posts", num_rows=3, dataset_type="tiktok-search",
                         columns=["id", "body"],
                         items=[{"id": "p1", "body": "first"},
                                {"id": "p2", "body": "second"},
                                {"id": 3, "body": "third"}])  # a numeric item ID
    processor, output = make_processor(tmp_path, metadata, {"join_source": True}, source)

    processor.process()

    fieldnames, rows = read_result(output)
    assert fieldnames == ["media_url", "media_filename", "media_post_ids",
                          "media_download_successful", "media_source_matched", "id", "body"]

    # 1.jpg twice (once per item), 2.jpg once, 4.jpg once
    assert len(rows) == 4
    assert output.finished == 4
    # 4.jpg did not trace back to an item, so a partial-match warning is raised
    assert output.warning is not None
    assert "1 of 3 media file(s) could not be traced" in output.warning

    by_file = {}
    for row in rows:
        by_file.setdefault(row["media_filename"], []).append(row)

    assert sorted(row["body"] for row in by_file["1.jpg"]) == ["first", "second"]
    assert all(row["media_source_matched"] == "True" for row in by_file["1.jpg"])
    # the metadata column keeps listing every item, prefixed and untouched
    assert by_file["1.jpg"][0]["media_post_ids"] == "p1, p2"

    # a numeric item ID in the dataset still matches the text one in the metadata
    assert by_file["2.jpg"][0]["body"] == "third"

    # nothing to trace 4.jpg back to, but it is not dropped
    assert by_file["4.jpg"][0]["media_source_matched"] == "False"
    assert by_file["4.jpg"][0]["body"] == ""


def test_process_media_without_post_id_renders_empty_not_none(tmp_path):
    """
    Media with no traceable item (e.g. an Instagram ad) has a null post id in
    the archive. It must show as an empty post-id cell and an unmatched row, not
    the literal text "None".
    """
    metadata = make_metadata(items=[
        ("ad.jpg", [None], "http://example.com/ad.jpg"),
        ("ok.jpg", ["p1"], "http://example.com/ok.jpg"),
    ])
    source = FakeDataset(key="posts", num_rows=1, columns=["id", "body"],
                         items=[{"id": "p1", "body": "first"}])
    processor, output = make_processor(tmp_path, metadata, {"join_source": True}, source)

    processor.process()

    _, rows = read_result(output)
    by_file = {r["media_filename"]: r for r in rows}
    assert by_file["ad.jpg"]["media_post_ids"] == ""
    assert by_file["ad.jpg"]["media_source_matched"] == "False"
    assert by_file["ad.jpg"]["body"] == ""
    assert by_file["ok.jpg"]["media_source_matched"] == "True"


def test_process_no_warning_when_all_media_traced(tmp_path):
    """When every media file traces back to an item, the dataset finishes cleanly."""
    metadata = make_metadata(items=[
        ("1.jpg", ["p1"], "http://example.com/1.jpg"),
        ("2.jpg", ["p2"], "http://example.com/2.jpg"),
    ])
    source = FakeDataset(key="posts", num_rows=2, columns=["id", "body"],
                         items=[{"id": "p1", "body": "first"}, {"id": "p2", "body": "second"}])
    processor, output = make_processor(tmp_path, metadata, {"join_source": True}, source)

    processor.process()

    assert output.warning is None
    assert output.finished == 2


def test_process_without_join(tmp_path):
    """Turning the join off gives the metadata on its own."""
    metadata = make_metadata(items=[("1.jpg", ["p1"], "http://example.com/1.jpg")])
    source = FakeDataset(key="posts", num_rows=1, columns=["id", "body"],
                         items=[{"id": "p1", "body": "first"}])
    processor, output = make_processor(tmp_path, metadata, {"join_source": False}, source)

    processor.process()

    fieldnames, rows = read_result(output)
    assert fieldnames == ["media_url", "media_filename", "media_post_ids",
                          "media_download_successful"]
    assert len(rows) == 1
    assert output.finished == 1


def test_process_warns_when_nothing_matches(tmp_path):
    metadata = make_metadata(items=[("1.jpg", ["p1"], "http://example.com/1.jpg")])
    source = FakeDataset(key="posts", num_rows=1, columns=["id", "body"],
                         items=[{"id": "somethingelse", "body": "first"}])
    processor, output = make_processor(tmp_path, metadata, {"join_source": True}, source)

    processor.process()

    _, rows = read_result(output)
    assert len(rows) == 1
    assert rows[0]["media_source_matched"] == "False"
    assert output.warning is not None
    assert "None of the 1 media file(s) could be traced back" in output.warning


def test_process_errors_without_metadata_file(tmp_path):
    processor, output = make_processor(tmp_path, metadata=None)

    processor.process()

    assert output.error == "Unable to identify metadata file"
    assert not output.get_results_path().exists()


# -- crediting the right dataset when a preset builds a helper --

def test_video_downloader_honours_from_dataset_override(tmp_path):
    """
    The downloader normally credits the dataset it ran on, but a preset can name
    a different one, because the dataset it ran on may be a helper.
    """
    from processors.visualisation.download_videos import VideoDownloaderPlus

    credited = []

    class DatasetStub:
        def update_status(self, *args, **kwargs):
            pass

        def new_media_metadata(self, processor_type=None, from_dataset=None):
            credited.append(from_dataset)
            return MediaArchiveMetadata(from_dataset=from_dataset)

    downloader = VideoDownloaderPlus.__new__(VideoDownloaderPlus)
    downloader.dataset = DatasetStub()
    downloader.source_dataset = SimpleNamespace(key="helper")

    downloader.parameters = {"_from_dataset": "original"}
    downloader._save_metadata({}, tmp_path)

    downloader.parameters = {}
    downloader._save_metadata({}, tmp_path)

    assert credited == ["original", "helper"]


@pytest.mark.parametrize("dataset_type,parameters,expected", [
    # the id column is the items' own `id`, so the original can be credited
    ("tiktok-search", {}, "original"),
    ("tiktok-urls-search", {}, "original"),
    ("upload-search", {"column": "id"}, "original"),
    # a different id column: the recorded post IDs would not match that
    # dataset's items, so the helper stays the right answer
    ("upload-search", {"column": "tiktok_post_id"}, None),
])
def test_tiktok_preset_credits_original_only_when_ids_line_up(dataset_type, parameters, expected):
    from processors.visualisation.download_tiktok_video import TikTokVideoDownloader

    preset = TikTokVideoDownloader.__new__(TikTokVideoDownloader)
    preset.source_dataset = SimpleNamespace(type=dataset_type, key="original")
    preset.parameters = {"amount": 10, **parameters}

    stages = preset.get_processor_pipeline()
    video_stage = next(stage for stage in stages if stage["type"] == "video-downloader")

    assert video_stage["parameters"].get("_from_dataset") == expected


def test_tiktok_preset_reads_video_downloader_metadata():
    """
    The preset has the video downloader write its archive, so it reads that
    archive the same way the video downloader would.
    """
    from processors.visualisation.download_tiktok_video import TikTokVideoDownloader
    from processors.visualisation.download_videos import VideoDownloaderPlus

    item = {"filename": "7241234567890.mp4", "post_ids": ["7241234567890"],
            "url": "https://tiktok.com/x", "extra": {"title": "a video", "downloader": "yt_dlp"}}
    failure = {"post_ids": ["7241234567891"], "reason": "error",
               "reason_description": "no video found", "url": "https://tiktok.com/y"}

    assert (list(TikTokVideoDownloader.map_metadata("7241234567890.mp4", item))
            == list(VideoDownloaderPlus.map_metadata("7241234567890.mp4", item)))
    assert (list(TikTokVideoDownloader.map_failure_metadata(failure))
            == list(VideoDownloaderPlus.map_failure_metadata(failure)))
