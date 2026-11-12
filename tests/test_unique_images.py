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

    :param dict images:  Path within the archive -> the bytes of that image.
      Two images with the same bytes are duplicates of one another.
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
        path.parent.mkdir(parents=True, exist_ok=True)
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


def test_the_kept_image_keeps_its_own_url_whatever_order_the_metadata_lists(tmp_path):
    """
    The metadata file does not list the kept image before its duplicates.

    Which image is kept depends on the order the archive is read in, not on the
    order the metadata was written in, so the entry for a duplicate can come
    first. The first entry written for a file decides its `url`, so reading
    them in the order they happen to be in would make the duplicate's URL the
    URL of the image that is kept, and demote the real one to an 'other' URL.
    """
    written = run_filter(
        tmp_path,
        # a.jpg is read first, so it is the image that is kept
        {"a.jpg": b"same", "b.jpg": b"same"},
        # but b.jpg, the duplicate, is the first one the metadata describes
        [("b.jpg", ["2"], "http://host/b.jpg", None),
         ("a.jpg", ["1"], "http://host/a.jpg", None)],
    )

    kept = written.get_entry("a.jpg")
    assert kept["url"] == "http://host/a.jpg"
    assert kept["extra"]["other_urls"] == ["http://host/b.jpg"]
    assert sorted(kept["post_ids"]) == ["1", "2"]


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


"""
What happens to images that arrive with the same name.

The filter writes every image it keeps into one folder, so images that come in
folders of their own can come in with the same name: a video's frames are
numbered from the start of that video, and two videos can have the same name
but for their extension. Copying the second image over the first destroys an
image that was no duplicate of anything, and the count the filter reports
still counts it.
"""


def test_images_with_the_same_name_in_different_folders_are_all_kept(tmp_path):
    run_filter(
        tmp_path,
        {"clip.mp4/frame_1.jpeg": b"first video", "clip.webm/frame_1.jpeg": b"second video",
         "other.mp4/frame_1.jpeg": b"third video"},
        # the metadata of an archive of video frames describes the videos, not
        # the frames, so no entry here is named after a file above
        [("clip.mp4", ["1"], "http://host/clip.mp4", None),
         ("clip.webm", ["2"], "http://host/clip.webm", None),
         ("A.mp4", ["3"], "http://host/A.mp4", None),
         ("a.mp4", ["4"], "http://host/a.mp4", None),
         ("other.mp4", ["5"], "http://host/other.mp4", None)],
    )

    kept = [path for path in (tmp_path / "staging").iterdir() if path.name != ".metadata.json"]
    assert sorted(path.read_bytes() for path in kept) == [b"first video", b"second video", b"third video"]


def test_images_named_alike_but_for_their_capitals_are_kept_apart(tmp_path):
    """
    The filter chooses the names in its own archive, so it decides whether that
    archive can be unpacked whole. Two names that differ only in their capitals
    are two files on the Linux server that writes them and one file on the
    Windows or macOS machine that unpacks them.
    """
    run_filter(
        tmp_path,
        {"A.mp4/A_frame_1.jpeg": b"one video", "a.mp4/a_frame_1.jpeg": b"another video"},
        [("A.mp4", ["1"], "http://host/A.mp4", None),
         ("a.mp4", ["2"], "http://host/a.mp4", None)],
    )

    written = [path.name for path in (tmp_path / "staging").iterdir() if path.name != ".metadata.json"]
    folded = {name.lower() for name in written}
    assert len(folded) == len(written), ("the filter put these in one folder, so unpacking its archive "
                                        f"on Windows or macOS would lose one: {sorted(written)}")
