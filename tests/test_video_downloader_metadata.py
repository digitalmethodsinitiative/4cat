"""
Tests for how the video downloader writes its archive metadata and reuses the
metadata of earlier downloads.

The downloader is built with `__new__` and given stand-ins for the few
attributes it uses, so none of the worker machinery (database, job queue,
config) has to be started up.
"""
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
