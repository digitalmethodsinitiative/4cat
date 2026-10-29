"""
Tests for which URLs the image downloader records in its archive metadata.

The downloader is built with `__new__` and given only the redirects it has
seen, so none of the worker machinery has to be started up.
"""
from common.lib.archive_metadata import MediaArchiveMetadata
from common.lib.media_archive_library import MediaArchiveLibrary
from processors.visualisation.download_images import ImageDownloader


def make_downloader(redirects=None):
    downloader = ImageDownloader.__new__(ImageDownloader)
    downloader.url_redirects = redirects or {}
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
