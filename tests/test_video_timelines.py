"""
Tests for the video timeline renderer
"""
from pathlib import Path
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


"""
Which video a frame came from.

A timeline is grouped by the video its frames came from and labelled with what
that video is called, so the two halves have to agree on how a video is named.
A frame's own metadata entry says which video it was cut from. The folder it
sits in cannot be trusted for that any more: two videos whose names differ only
in their capitals are one name to some file systems, so one of their two folders
is given a name no video has. Archives written before the frames had entries of
their own are still read the old way, by their folders.
"""


def frame_metadata(entries):
    """Metadata as an archive of frames carries it: an entry per frame"""
    metadata = MediaArchiveMetadata(from_dataset="posts")
    for filename, source_file, post_ids in entries:
        metadata.add_item(filename, post_ids=post_ids, source_file=source_file)
    return metadata


def test_labels_are_found_for_an_archive_of_frames(processor):
    labels = processor.get_video_labels(frame_metadata([
        ("clip_mp4_frame_0000001.jpeg", "clip.mp4", ["1"]),
        ("clip_mp4_frame_0000002.jpeg", "clip.mp4", ["1"]),
    ]))

    assert labels["clip.mp4"] == "1"


def test_a_frame_is_traced_to_its_video_by_its_own_entry():
    metadata = frame_metadata([("clip_mp4_frame_0000001.jpeg", "clip.mp4", ["1"])])

    # the folder is named `a-1.mp4` here, which is no video's name at all
    assert VideoTimelines.video_for(metadata, Path("a-1.mp4/clip_mp4_frame_0000001.jpeg")) == "clip.mp4"


def test_a_frame_nothing_is_said_about_falls_back_to_its_folder():
    """An archive written before the frames had entries of their own"""
    old_archive = make_metadata([("clip.mp4", ["1"])])
    frame = Path("clip.mp4/video_frame_0000001.jpeg")

    assert VideoTimelines.video_for(old_archive, frame) == "clip.mp4"
    # an upload of loose video files has no metadata at all
    assert VideoTimelines.video_for(None, frame) == "clip.mp4"


def test_the_label_is_found_under_the_name_a_frame_is_traced_to(processor):
    """
    The halves agreeing is the whole point: a frame whose video is found but
    whose label is not is a timeline with the wrong name drawn on it.
    """
    metadata = frame_metadata([
        ("clip_mp4_frame_0000001.jpeg", "clip.mp4", ["1"]),
        ("clip_mp4_frame_0000002.jpeg", "clip.mp4", ["1"]),
    ])

    labels = processor.get_video_labels(metadata)
    video = VideoTimelines.video_for(metadata, Path("clip.mp4/clip_mp4_frame_0000001.jpeg"))

    assert labels[video] == "1"
