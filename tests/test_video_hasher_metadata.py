"""
Tests for putting a video hasher's collages next to its hash rows

The hasher writes a row of hashes per video, keyed by the video's own file
name, and a collage image named after it. The two names are not the same, so
each collage records the video it was made from, and the image wall reads that
rather than working backwards from the collage's name.
"""
import json
import pathlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from common.lib.archive_metadata import MediaArchiveMetadata
from processors.visualisation.image_category_wall import ImageCategoryWallGenerator


def collage_metadata(entries):
    """Metadata as the hasher writes it: an entry per collage image"""
    metadata = MediaArchiveMetadata(from_dataset="posts")
    for collage, video in entries:
        metadata.add_item(collage, post_ids=["1"], source_file=video)
    return metadata


@pytest.fixture
def staging_area(tmp_path):
    area = tmp_path / "staging"
    area.mkdir()
    return area


def make_wall(metadata):
    """An image wall that reads the metadata it is given, and nothing else"""
    wall = ImageCategoryWallGenerator.__new__(ImageCategoryWallGenerator)
    wall.get_media_metadata = lambda dataset=None: metadata
    return wall


def test_each_collage_is_found_by_the_video_it_was_made_from(staging_area):
    """
    `clip.mp4` and `clip.webm` are two videos with one stem, so their collages
    cannot both be named after the stem and neither name says which video it
    came from. The metadata does.
    """
    for collage in ("clip_mp4.jpg", "clip_webm.jpg"):
        staging_area.joinpath(collage).touch()
    wall = make_wall(collage_metadata([("clip_mp4.jpg", "clip.mp4"),
                                       ("clip_webm.jpg", "clip.webm")]))

    collages = wall.map_collages_to_videos(MagicMock(), staging_area)

    # the ids in video_hashes.csv are the video file names
    assert collages["clip.mp4"] == [staging_area / "clip_mp4.jpg"]
    assert collages["clip.webm"] == [staging_area / "clip_webm.jpg"]


def test_the_hashes_file_is_not_offered_as_a_collage(staging_area):
    """The archive holds the hash rows too, and they are not an image"""
    staging_area.joinpath("video_hashes.csv").touch()
    staging_area.joinpath("clip_mp4.jpg").touch()
    wall = make_wall(collage_metadata([("clip_mp4.jpg", "clip.mp4")]))

    collages = wall.map_collages_to_videos(MagicMock(), staging_area)

    assert list(collages) == ["clip.mp4"]


def test_a_collage_that_names_no_video_is_left_out(staging_area):
    """
    Rather than be mapped under a name no video has, where it would be drawn
    for the wrong row.
    """
    metadata = MediaArchiveMetadata(from_dataset="posts")
    metadata.add_item("mystery.jpg", post_ids=["1"])
    wall = make_wall(metadata)

    assert list(wall.map_collages_to_videos(MagicMock(), staging_area)) == []


def test_an_archive_without_metadata_still_finds_mp4_collages(staging_area):
    """
    Collages written before they had metadata are named after the video's stem
    alone, so the extension has to be assumed. `.mp4` is the guess, which is
    why giving the collages metadata is worth doing.
    """
    staging_area.joinpath("clip.jpg").touch()
    wall = make_wall(None)

    collages = wall.map_collages_to_videos(MagicMock(), staging_area)

    assert collages["clip.mp4"] == [staging_area / "clip.jpg"]
    # a video that was not an .mp4 goes on finding nothing, as it always did
    assert "clip.webm" not in collages


def test_a_video_that_could_not_be_hashed_is_recorded_without_a_collage(staging_area):
    """
    A video ffmpeg cannot read gets no collage, but the posts counting on it
    are still named, so the researcher can tell a missing image from a video
    that was never there. Failures are not items, so the mapping below ignores
    them rather than offering a collage that does not exist.
    """
    metadata = MediaArchiveMetadata(from_dataset="posts")
    metadata.add_item("good_mp4.jpg", post_ids=["1"], source_file="good.mp4")
    metadata.add_failure(post_ids=["2"], source_file="broken.mp4",
                         reason="no_frames_extracted",
                         reason_description="ffmpeg could not read a frame from broken.mp4")
    staging_area.joinpath("good_mp4.jpg").touch()

    collages = make_wall(metadata).map_collages_to_videos(MagicMock(), staging_area)

    assert list(collages) == ["good.mp4"]

    failure = next(iter(metadata.iter_failures()))
    assert failure["source_file"] == "broken.mp4"
    assert failure["post_ids"] == ["2"]


"""
What happens to the run when one video cannot be hashed.

One unreadable video is not a reason to fail the whole dataset: the others are
hashed, the archive is written, and the dataset finishes with a warning. The
unreadable one is in the metadata as a failure, so it is not simply absent.
"""


def run_hasher(tmp_path, monkeypatch, videos, unreadable=()):
    """
    Hash `videos`, with the names in `unreadable` failing in ffmpeg

    :return tuple:  The staging area written to, the keyword arguments the
      archive was finished with, and the processor, whose dataset mock records
      how the run ended
    """
    from videohash.exceptions import FFmpegFailedToExtractFrames
    from processors.visualisation import video_hasher as module

    staging_area = tmp_path / "staging"
    staging_area.mkdir()
    collage_source = tmp_path / "collage.jpg"
    collage_source.write_text("collage")

    class FakeVideoHash:
        def __init__(self, path, **kwargs):
            if pathlib.Path(path).name in unreadable:
                raise FFmpegFailedToExtractFrames("no frames here")
            self.collage_path = str(collage_source)
            self.hash = "0b1010"
            self.video_duration = 3.5

        def delete_storage_path(self):
            pass

    monkeypatch.setattr(module, "VideoHash", FakeVideoHash)

    items = []
    for name in videos:
        video = tmp_path / name
        video.write_text("video")
        items.append(SimpleNamespace(file=video))

    written = {}
    processor = module.VideoHasher.__new__(module.VideoHasher)
    processor.parameters = {"frame_interval": 1, "amount": 0, "save_annotations": False}
    processor.interrupted = False
    processor.log = MagicMock()
    processor.dataset = MagicMock()
    processor.dataset.get_staging_area.side_effect = [tmp_path / "videos", staging_area]
    (tmp_path / "videos").mkdir()
    processor.source_dataset = MagicMock()
    processor.source_dataset.num_rows = len(items)
    processor.source_dataset.key = "videoskey"
    processor.source_dataset.iterate_items.return_value = items
    processor.get_media_metadata = lambda dataset=None: None
    processor.dataset.new_media_metadata.side_effect = (
        lambda from_dataset, processor_type, filename=".metadata.json": MediaArchiveMetadata.new(
            processor_type=processor_type, from_dataset=from_dataset, filename=filename))
    processor.write_archive_and_finish = lambda files, **kwargs: written.update(kwargs)

    module.VideoHasher.process(processor)
    return staging_area, written, processor


def test_one_unreadable_video_warns_instead_of_failing_the_run(tmp_path, monkeypatch):
    staging_area, written, processor = run_hasher(
        tmp_path, monkeypatch, ["good.mp4", "broken.mp4"], unreadable=["broken.mp4"])

    processor.dataset.finish_with_error.assert_not_called()
    assert written["num_items"] == 1
    assert "1 of 2" in written["warning"]
    # the run was not finished early, so the archive holds the other collage
    assert (staging_area / "good_mp4.jpg").exists()


def test_the_unreadable_video_is_in_the_metadata_as_a_failure(tmp_path, monkeypatch):
    staging_area, _, _ = run_hasher(tmp_path, monkeypatch,
                                    ["good.mp4", "broken.mp4"], unreadable=["broken.mp4"])
    written = json.loads((staging_area / ".metadata.json").read_text(encoding="utf-8"))

    assert list(written["items"]) == ["good_mp4.jpg"]
    assert [failure["source_file"] for failure in written["failures"]] == ["broken.mp4"]


def test_no_warning_when_every_video_is_hashed(tmp_path, monkeypatch):
    _, written, _ = run_hasher(tmp_path, monkeypatch, ["a.mp4", "b.webm"])

    assert written["num_items"] == 2
    assert written["warning"] is None
