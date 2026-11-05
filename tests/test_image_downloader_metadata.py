"""
Tests for which URLs the image downloader records in its archive metadata.

The downloader is built with `__new__` and given only the redirects it has
seen, so none of the worker machinery has to be started up.
"""
import pytest
import requests

from common.lib.archive_metadata import MediaArchiveMetadata
from common.lib.helpers import UniqueFilenames
from common.lib.media_archive_library import MediaArchiveLibrary
from processors.visualisation.download_images import ImageDownloader


def make_downloader(redirects=None, filenames=None, staging_filenames=None):
    downloader = ImageDownloader.__new__(ImageDownloader)
    downloader.url_redirects = redirects or {}
    downloader.filenames = filenames or {}
    downloader.staging_filenames = staging_filenames or UniqueFilenames()
    return downloader


def test_redirected_url_is_recorded_with_the_dataset_url_as_other_url():
    downloader = make_downloader({
        "http://example.com/a.jpg": "https://example.com/a.jpg",
        "https://example.com/a.jpg": "https://cdn.example.com/a.jpg",
    })

    url, extra = downloader.urls_for_metadata("http://example.com/a.jpg")

    # where the file was downloaded from, after following every redirect
    assert url == "https://cdn.example.com/a.jpg"
    # the URL as it appeared in the dataset
    assert extra == {"other_urls": ["http://example.com/a.jpg"]}


def test_url_without_redirect_has_no_other_urls():
    url, extra = make_downloader().urls_for_metadata("https://example.com/a.jpg")
    assert url == "https://example.com/a.jpg"
    assert extra == {}


def test_correcting_an_extension_does_not_take_another_url_s_filename(tmp_path):
    """
    `photo.png` and `photo.jpg` are unique names until PIL says both files are
    really JPEG. Renaming the second onto the first would overwrite that image
    and leave its posts pointing at this one, so it gets a free name.
    """
    names = UniqueFilenames(tmp_path)
    downloader = make_downloader(
        filenames={
            "http://a/photo.png": names.reserve("photo.png"),
            "http://b/photo.jpg": names.reserve("photo.jpg"),
        },
        staging_filenames=names,
    )

    first = downloader.filename_for_extension("http://a/photo.png", ".jpeg")
    downloader.filenames["http://a/photo.png"] = first
    second = downloader.filename_for_extension("http://b/photo.jpg", ".jpeg")

    assert first == "photo.jpeg"
    assert second != first
    assert second.endswith(".jpeg")


def test_right_extension_keeps_the_same_filename(tmp_path):
    names = UniqueFilenames(tmp_path)
    downloader = make_downloader(
        filenames={"http://a/photo.jpeg": names.reserve("photo.jpeg")},
        staging_filenames=names,
    )
    assert downloader.filename_for_extension("http://a/photo.jpeg", ".jpeg") == "photo.jpeg"


def test_correcting_an_extension_avoids_a_file_already_on_disk(tmp_path):
    """A file already written by an earlier download is a collision too."""
    tmp_path.joinpath("photo.jpeg").touch()
    names = UniqueFilenames(tmp_path)
    downloader = make_downloader(
        filenames={"http://a/photo.png": names.reserve("photo.png")},
        staging_filenames=names,
    )
    assert downloader.filename_for_extension("http://a/photo.png", ".jpeg") != "photo.jpeg"


@pytest.mark.parametrize("context, expected_reason", [
    (requests.exceptions.Timeout("too slow"), "timeout"),
    (requests.exceptions.SSLError("bad cert"), "ssl_error"),
    (requests.exceptions.TooManyRedirects("round and round"), "too_many_redirects"),
    (requests.exceptions.ConnectionError("no route"), "connection_error"),
    # requests' hierarchy overlaps, so anything not matched exactly stays generic
    (requests.exceptions.ConnectTimeout("both at once"), "error"),
    (ValueError("something else entirely"), "error"),
])
def test_request_failures_are_recorded_by_kind(context, expected_reason):
    """
    The metadata says *why* a download failed, so a reader can tell a timeout
    from a dead link without going through the dataset log.
    """
    reason, description = ImageDownloader.request_failure_reason(context, "http://a/photo.jpg")
    assert reason == expected_reason
    # the description names the URL and carries the underlying error
    assert "http://a/photo.jpg" in description
    assert str(context) in description


def test_two_urls_leading_to_one_file_keep_both_their_posts():
    """
    If two URLs do end up at the same file, the second must not overwrite the
    first's entry: both posts need to keep pointing at the image, and both
    URLs need to find it.
    """
    metadata = MediaArchiveMetadata.new(processor_type="image-downloader", from_dataset="posts")
    metadata.add_item("photo.jpeg", post_ids=["p1"], url="http://a/photo.png", merge=True)
    metadata.add_item("photo.jpeg", post_ids=["p2"], url="http://b/photo.jpg", merge=True)

    entry = metadata.get_entry("photo.jpeg")
    assert entry["post_ids"] == ["p1", "p2"]
    assert entry["url"] == "http://a/photo.png"
    assert entry["extra"]["other_urls"] == ["http://b/photo.jpg"]

    library = MediaArchiveLibrary([metadata])
    for found_by in ("http://a/photo.png", "http://b/photo.jpg"):
        assert library.find(found_by).is_success


def test_redirected_image_can_be_found_by_either_url():
    """Both downloads and failures can be looked up by the dataset's URL or the final one."""
    downloader = make_downloader({
        "http://example.com/a.jpg": "https://cdn.example.com/a.jpg",
        "http://example.com/b.jpg": "https://cdn.example.com/b.jpg",
    })
    metadata = MediaArchiveMetadata.new(processor_type="image-downloader", from_dataset="posts")

    url, extra = downloader.urls_for_metadata("http://example.com/a.jpg")
    metadata.add_item("a.jpg", post_ids=["p1"], url=url, extra=extra, replace=True)
    url, extra = downloader.urls_for_metadata("http://example.com/b.jpg")
    metadata.add_failure(post_ids=["p2"], reason="error", url=url, extra=extra)

    library = MediaArchiveLibrary([metadata])
    for found_by in ("http://example.com/a.jpg", "https://cdn.example.com/a.jpg"):
        hit = library.find(found_by)
        assert hit.is_success
        assert [filename for filename, _ in hit.entries] == ["a.jpg"]
    for found_by in ("http://example.com/b.jpg", "https://cdn.example.com/b.jpg"):
        hit = library.find(found_by)
        assert not hit.is_success
        assert hit.reasons == {"error"}
