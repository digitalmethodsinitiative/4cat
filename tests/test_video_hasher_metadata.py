"""
Tests for putting a video hasher's collages next to its hash rows

The hasher writes a row of hashes per video, keyed by the video's own file
name, and a collage image named after it. The two names are not the same, so
each collage records the video it was made from, and the image wall reads that
rather than working backwards from the collage's name.
"""
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
