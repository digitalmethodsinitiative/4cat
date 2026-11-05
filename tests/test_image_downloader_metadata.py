"""
Tests for which URLs the image downloader records in its archive metadata.

The downloader is built with `__new__` and given only the redirects it has
seen, so none of the worker machinery has to be started up.
"""
from common.lib.archive_metadata import MediaArchiveMetadata
from common.lib.media_archive_library import MediaArchiveLibrary
from processors.visualisation.download_images import ImageDownloader


def make_downloader(redirects=None, filenames=None, staging_area=None):
    downloader = ImageDownloader.__new__(ImageDownloader)
    downloader.url_redirects = redirects or {}
    downloader.filenames = filenames or {}
    downloader.staging_area = staging_area
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
    downloader = make_downloader(
        filenames={"http://a/photo.png": "photo.png", "http://b/photo.jpg": "photo.jpg"},
        staging_area=tmp_path,
    )
    seen = {"photo.png", "photo.jpg"}

    first = downloader.filename_for_extension("http://a/photo.png", ".jpeg", seen)
    downloader.filenames["http://a/photo.png"] = first
    second = downloader.filename_for_extension("http://b/photo.jpg", ".jpeg", seen)

    assert first == "photo.jpeg"
    assert second != first
    assert second.endswith(".jpeg")
    # the names they no longer use are free again, the ones they do use are taken
    assert seen == {first, second}


def test_right_extension_keeps_the_same_filename(tmp_path):
    downloader = make_downloader(
        filenames={"http://a/photo.jpeg": "photo.jpeg"}, staging_area=tmp_path
    )
    seen = {"photo.jpeg"}
    assert downloader.filename_for_extension("http://a/photo.jpeg", ".jpeg", seen) == "photo.jpeg"
    assert seen == {"photo.jpeg"}


def test_correcting_an_extension_avoids_a_file_already_on_disk(tmp_path):
    """A file already written by an earlier download is a collision too."""
    tmp_path.joinpath("photo.jpeg").touch()
    downloader = make_downloader(
        filenames={"http://a/photo.png": "photo.png"}, staging_area=tmp_path
    )
    seen = {"photo.png"}
    assert downloader.filename_for_extension("http://a/photo.png", ".jpeg", seen) != "photo.jpeg"


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
