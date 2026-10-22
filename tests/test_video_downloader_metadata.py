"""
Tests for how the video downloader writes its archive metadata and reuses the
metadata of earlier downloads.

The downloader is built with `__new__` and given stand-ins for the few
attributes it uses, so none of the worker machinery (database, job queue,
config) has to be started up.
"""
import zipfile
from types import SimpleNamespace

from common.lib.archive_metadata import MediaArchiveMetadata
from common.lib.media_archive_library import MediaArchiveLibrary
from processors.visualisation.download_videos import VideoDownloaderPlus


class DatasetStub:
    """Stands in for the dataset the downloader is producing."""

    def __init__(self):
        self.metadata = None
        self.logs = []

    def update_status(self, *args, **kwargs):
        pass

    def log(self, message):
        self.logs.append(message)

    def new_media_metadata(self, processor_type=None, from_dataset=None):
        self.metadata = MediaArchiveMetadata(from_dataset=from_dataset)
        return self.metadata


def make_downloader(parameters=None):
    downloader = VideoDownloaderPlus.__new__(VideoDownloaderPlus)
    downloader.dataset = DatasetStub()
    downloader.source_dataset = SimpleNamespace(key="posts")
    downloader.parameters = parameters or {}
    downloader.files_copied_from_library = {}
    return downloader


# -- writing metadata --

def test_file_reached_through_two_urls_keeps_posts_of_both(tmp_path):
    """
    When yt-dlp recognises a video it already downloaded for an earlier URL, the
    later URL lists the same file. Both URLs' posts must stay connected to it.
    """
    video = {"filename": "abc.mp4", "success": True, "metadata": {"id": "abc"}}
    urls = {
        "https://youtube.com/watch?v=abc": {
            "post_ids": {"p1"}, "success": True, "downloader": "yt_dlp", "files": [video],
        },
        # not marked successful, because nothing new was downloaded for it
        "https://youtu.be/abc": {
            "post_ids": {"p2"}, "success": False, "downloader": "yt_dlp", "files": [video],
        },
    }
    downloader = make_downloader()
    downloader._save_metadata(urls, tmp_path)

    metadata = downloader.dataset.metadata
    assert metadata.post_ids_for("abc.mp4") == ["p1", "p2"]
    assert metadata.get_entry("abc.mp4")["url"] == "https://youtube.com/watch?v=abc"
    assert metadata.get_entry("abc.mp4")["extra"]["other_urls"] == ["https://youtu.be/abc"]
    assert metadata.failures == []


def test_copied_video_does_not_carry_the_earlier_archives_other_urls():
    """
    Other URLs recorded by an earlier download came from that dataset's posts,
    so they are not copied into this archive's metadata along with the file.
    """
    earlier = MediaArchiveMetadata(SimpleNamespace(parameters={}))
    earlier.add_item("abc.mp4", post_ids=["p1"], url="https://youtube.com/watch?v=abc",
                     extra={"title": "a video", "downloader": "yt_dlp"})
    earlier.add_item("abc.mp4", post_ids=["p2"], url="https://youtu.be/abc", merge=True)
    hit = MediaArchiveLibrary([earlier]).find("https://youtube.com/watch?v=abc")

    fields = VideoDownloaderPlus._copied_url_fields(hit)

    assert fields["files"][0]["metadata"] == {"title": "a video"}
    assert fields["downloader"] == "yt_dlp"
    # the earlier archive itself is left as it was
    assert earlier.get_entry("abc.mp4")["extra"]["other_urls"] == ["https://youtu.be/abc"]


# -- reusing earlier downloads --

def old_not_a_video_archive(also_indirect):
    """
    Metadata of a video download made before archive metadata had a schema
    version, in which a URL was found not to be a video.
    """
    previous_run = SimpleNamespace(parameters={"also_indirect": also_indirect})
    metadata = MediaArchiveMetadata(previous_run)
    metadata._populate_from_raw({
        "https://example.com/page": {
            "success": False, "retry": False, "also_indirect": also_indirect,
            "post_ids": ["p1"], "error": "Not a video",
        },
    })
    return metadata


def test_url_an_old_download_found_not_to_be_a_video_is_skipped(tmp_path):
    library = MediaArchiveLibrary([old_not_a_video_archive("none")])
    urls = {"https://example.com/page": {"post_ids": {"p9"}}}
    downloader = make_downloader({"also_indirect": "none"})

    result = downloader._try_copy_from_library("https://example.com/page", urls, library, tmp_path)

    assert result["skip"] is True
    assert urls["https://example.com/page"]["reason"] == "not_a_video"


def test_url_is_tried_again_when_this_run_allows_yt_dlp_more_urls(tmp_path):
    library = MediaArchiveLibrary([old_not_a_video_archive("none")])
    urls = {"https://example.com/page": {"post_ids": {"p9"}}}
    downloader = make_downloader({"also_indirect": "all"})

    result = downloader._try_copy_from_library("https://example.com/page", urls, library, tmp_path)

    assert result["skip"] is False


def earlier_video_archive(tmp_path, key, urls):
    """
    An earlier video download whose zip holds one video, `abc.mp4`, that the
    given URLs all led to.
    """
    folder = tmp_path / key
    folder.mkdir()
    zip_path = folder / "results.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("abc.mp4", b"video bytes")

    dataset = SimpleNamespace(key=key, parameters={}, get_results_path=lambda: zip_path)
    metadata = MediaArchiveMetadata(dataset)
    for i, url in enumerate(urls):
        metadata.add_item("abc.mp4", post_ids=[f"{key}-{i}"], url=url,
                          extra={"downloader": "yt_dlp"}, merge=True)
    return metadata


def test_video_reached_through_two_urls_is_copied_once(tmp_path):
    """
    An earlier download reached one video through two URLs. When this dataset
    links to both, the video is found through either URL but copied once.
    """
    library = MediaArchiveLibrary([earlier_video_archive(
        tmp_path, "earlier", ["https://youtube.com/watch?v=abc", "https://youtu.be/abc"])])
    staging = tmp_path / "staging"
    staging.mkdir()
    urls = {
        "https://youtube.com/watch?v=abc": {"post_ids": {"p1"}},
        "https://youtu.be/abc": {"post_ids": {"p2"}},
    }
    downloader = make_downloader()

    first = downloader._try_copy_from_library("https://youtube.com/watch?v=abc", urls, library, staging)
    second = downloader._try_copy_from_library("https://youtu.be/abc", urls, library, staging)

    assert (first["copied"], first["count"]) == (True, 1)
    # found through the file's other URLs, but the video is already there
    assert (second["copied"], second["count"]) == (True, 0)
    assert [file.name for file in staging.iterdir()] == ["abc.mp4"]

    # both URLs' posts end up connected to the one file
    downloader._save_metadata(urls, staging)
    metadata = downloader.dataset.metadata
    assert metadata.post_ids_for("abc.mp4") == ["p1", "p2"]
    assert metadata.get_entry("abc.mp4")["extra"]["other_urls"] == ["https://youtu.be/abc"]


def test_same_filename_from_a_different_earlier_download_is_not_copied_over(tmp_path):
    """
    Two earlier downloads can each hold a file of the same name, which may be
    different videos. Copying the second would overwrite the first, so that URL
    is downloaded again instead.
    """
    library = MediaArchiveLibrary([
        earlier_video_archive(tmp_path, "earlier1", ["https://example.com/one"]),
        earlier_video_archive(tmp_path, "earlier2", ["https://example.com/two"]),
    ])
    staging = tmp_path / "staging"
    staging.mkdir()
    urls = {"https://example.com/one": {"post_ids": {"p1"}}, "https://example.com/two": {"post_ids": {"p2"}}}
    downloader = make_downloader()

    first = downloader._try_copy_from_library("https://example.com/one", urls, library, staging)
    second = downloader._try_copy_from_library("https://example.com/two", urls, library, staging)

    assert first["copied"] is True
    assert second["copied"] is False
    assert "files" not in urls["https://example.com/two"]
