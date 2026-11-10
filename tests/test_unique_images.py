"""
Tests for the unique image filter, which keeps one image per duplicate group
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from common.lib.archive_metadata import MediaArchiveMetadata
from processors.filtering.unique_images import UniqueImageFilter


"""
What a kept image stands in for.

An image that is dropped as a duplicate takes its posts and its URLs with it,
so the filter adds both to the image kept in its place: a post that pointed at
the duplicate still has an image, and the image can still be found by the URL
the duplicate was downloaded from.
"""


def run_filter(tmp_path, images, metadata_entries):
    """
    Filter an image archive and read back the metadata file it writes

    :param dict images:  File name -> the bytes of that image. Two images with
      the same bytes are duplicates of one another.
    :param list metadata_entries:  (file name, post IDs, URL, extra) of the
      source archive's metadata
    :return MediaArchiveMetadata:  The metadata written for the filtered archive
    """
    source_metadata = MediaArchiveMetadata(from_dataset="posts")
    for filename, post_ids, url, extra in metadata_entries:
        source_metadata.add_item(filename, post_ids=post_ids, url=url, extra=extra)

    source_area = tmp_path / "source"
    source_area.mkdir()
    items = []
    for filename, content in images.items():
        path = source_area / filename
        path.write_bytes(content)
        items.append(SimpleNamespace(file=path))

    staging_area = tmp_path / "staging"
    staging_area.mkdir()

    processor = MagicMock()
    processor.parameters = {"hash-type": "file-hash"}
    processor.interrupted = False
    processor.source_dataset.num_rows = len(items)
    processor.source_dataset.iterate_items.return_value = items
    processor.get_media_metadata.return_value = source_metadata
    processor.dataset.get_staging_area.return_value = staging_area
    processor.dataset.new_media_metadata.side_effect = \
        lambda **kwargs: MediaArchiveMetadata(from_dataset=kwargs.get("from_dataset"))

    UniqueImageFilter.process(processor)

    written = MediaArchiveMetadata()
    written._populate_from_raw(json.loads((staging_area / ".metadata.json").read_text(encoding="utf-8")))
    return written


def test_duplicate_posts_and_urls_move_to_the_kept_image(tmp_path):
    written = run_filter(
        tmp_path,
        {"a.jpg": b"same", "b.jpg": b"same"},
        [("a.jpg", ["1"], "http://host/a.jpg", {"other_urls": ["http://host/a-redirect.jpg"]}),
         ("b.jpg", ["2"], "http://host/b.jpg", {"other_urls": ["http://host/b-redirect.jpg"]})],
    )

    assert list(written.items) == ["a.jpg"]
    kept = written.get_entry("a.jpg")
    assert kept["post_ids"] == ["1", "2"]
    assert kept["url"] == "http://host/a.jpg"
    # the order they are listed in says nothing; what matters is that every URL
    # either image could be found by leads to the one that is kept
    assert sorted(kept["extra"]["other_urls"]) == ["http://host/a-redirect.jpg",
                                                   "http://host/b-redirect.jpg",
                                                   "http://host/b.jpg"]


def test_the_kept_image_does_not_list_its_own_url_among_the_others(tmp_path):
    written = run_filter(
        tmp_path,
        {"a.jpg": b"same", "b.jpg": b"same"},
        [("a.jpg", ["1"], "http://host/a.jpg", None),
         ("b.jpg", ["2"], "http://host/a.jpg", None)],
    )

    kept = written.get_entry("a.jpg")
    assert kept["url"] == "http://host/a.jpg"
    assert "http://host/a.jpg" not in kept.get("extra", {}).get("other_urls", [])


def test_images_that_are_not_duplicates_are_all_kept(tmp_path):
    written = run_filter(
        tmp_path,
        {"a.jpg": b"one", "b.jpg": b"two"},
        [("a.jpg", ["1"], "http://host/a.jpg", None),
         ("b.jpg", ["2"], "http://host/b.jpg", None)],
    )

    assert sorted(written.items) == ["a.jpg", "b.jpg"]
    assert written.get_entry("b.jpg")["post_ids"] == ["2"]
    # the hash it was compared by is recorded, so a later run can reuse it
    assert written.get_entry("a.jpg")["extra"]["hash_type"] == "file-hash"
    assert written.get_entry("a.jpg")["extra"]["hash"] != written.get_entry("b.jpg")["extra"]["hash"]
