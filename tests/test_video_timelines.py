"""
Tests for the video timeline renderer
"""
from unittest.mock import MagicMock

import pytest

from common.lib.archive_metadata import MediaArchiveMetadata
from processors.visualisation import video_timelines
from processors.visualisation.video_timelines import VideoTimelines


"""
Finding back what is known about a video.

The frames of a video are in a folder of their own, and the timeline rendered
from them is labelled with whatever the dataset the video came from calls it.
The folder is named after the video file, so the metadata entry for that file
is what has to be found. That holds for two videos whose names differ in
nothing but the extension, which the folder names keep apart.
"""


class FakeSourceDataset:
    """The dataset the videos were downloaded from"""

    def __init__(self, items):
        self.type = "telegram-search"
        self.parameters = {}
        self._items = items

    def nearest(self, type_pattern):
        return self

    def iterate_items(self, processor=None, **kwargs):
        for item in self._items:
            yield dict(item)


def make_metadata(entries):
    metadata = MediaArchiveMetadata(from_dataset="posts")
    for filename, post_ids in entries:
        metadata.add_item(filename, post_ids=post_ids)
    return metadata


@pytest.fixture
def processor(monkeypatch):
    processor = VideoTimelines.__new__(VideoTimelines)
    processor.db = MagicMock()
    processor.modules = MagicMock()
    processor.dataset = MagicMock()
    monkeypatch.setattr(video_timelines, "DataSet",
                        lambda **kwargs: FakeSourceDataset([{"id": "1"}, {"id": "2"}]))
    return processor


def test_labels_are_found_by_the_folder_the_frames_are_in(processor):
    labels = processor.get_video_labels(make_metadata([("clip.mp4", ["1"])]))

    assert labels["clip.mp4"] == "1"
    # archives of scene frames, and frame archives made before the folders were
    # named after the whole file name, leave the extension off
    assert labels["clip"] == "1"


def test_videos_differing_only_in_extension_keep_their_own_label(processor):
    """
    `clip.mp4` and `clip.webm` are two videos, downloaded for two different
    items. Their frames are in two folders, and each timeline gets the label of
    its own video.
    """
    labels = processor.get_video_labels(make_metadata([("clip.mp4", ["1"]),
                                                       ("clip.webm", ["2"])]))

    assert labels["clip.mp4"] == "1"
    assert labels["clip.webm"] == "2"


def test_a_video_without_a_matching_item_keeps_its_name_as_label(processor):
    labels = processor.get_video_labels(make_metadata([("clip.mp4", ["unknown"])]))

    assert labels["clip.mp4"] == "clip"
