"""
Tests for the frame extractor, which writes a folder of frames per video
"""
import pathlib
import zipfile
from types import SimpleNamespace
from unittest.mock import MagicMock

from packaging import version

from backend.lib.processor import BasicProcessor
from processors.visualisation.video_frames import VideoFrames
from processors.visualisation.video_scene_frames import VideoSceneFrames


"""
What a video's frames folder is called.

Each video's frames go into a folder of their own, named after the video file.
Keeping the extension matters twice over: `clip.mp4` and `clip.webm` are two
videos and need two folders, and the name is how whatever reads the frames
later looks the video up in the metadata file, which records it by file name.
"""


def run_extractor(tmp_path, monkeypatch, video_names, archive_contents=None):
    """
    Extract frames from an archive of videos

    :return Path:  The folder the frames were written to
    """
    source_archive = tmp_path / "videos.zip"
    with zipfile.ZipFile(source_archive, "w") as archive:
        for filename in (archive_contents if archive_contents is not None else video_names):
            archive.writestr(filename, "content")

    videos = []
    for name in video_names:
        video = tmp_path / name
        video.write_text("content")
        videos.append(SimpleNamespace(file=video))

    staging_area = tmp_path / "staging"
    staging_area.mkdir()

    monkeypatch.setattr("processors.visualisation.video_frames.shutil.which", lambda path: "/usr/bin/ffmpeg")
    monkeypatch.setattr("shutil.make_archive", lambda *args, **kwargs: None)

    processor = MagicMock()
    processor.parameters = {"frame_interval": 1.0, "frame_size": "no_modify"}
    processor.interrupted = False
    processor.source_dataset.num_rows = len(videos)
    processor.source_dataset.get_results_path.return_value = source_archive
    processor.source_dataset.iterate_items.return_value = videos
    processor.dataset.get_staging_area.return_value = staging_area
    processor.dataset.get_results_path.return_value = tmp_path / "results.zip"
    processor.extract_archived_file_by_name = \
        lambda *args: BasicProcessor.extract_archived_file_by_name(processor, *args)
    processor.run_interruptable_process.return_value = SimpleNamespace(stdout=b"", stderr=b"", returncode=0)

    VideoFrames.process(processor)
    return staging_area / "frames"


def test_a_frames_folder_is_named_after_the_video_file(tmp_path, monkeypatch):
    frames = run_extractor(tmp_path, monkeypatch, ["clip.mp4"])

    assert [folder.name for folder in frames.iterdir() if folder.is_dir()] == ["clip.mp4"]


def test_videos_differing_only_in_extension_get_a_folder_each(tmp_path, monkeypatch):
    frames = run_extractor(tmp_path, monkeypatch, ["clip.mp4", "clip.webm"])

    assert sorted(folder.name for folder in frames.iterdir() if folder.is_dir()) == ["clip.mp4", "clip.webm"]


def test_the_videos_metadata_is_copied_along(tmp_path, monkeypatch):
    """Without it the frames cannot be traced back to the items the videos were found in"""
    frames = run_extractor(tmp_path, monkeypatch, ["clip.mp4"],
                           archive_contents=[".metadata.json", "clip.mp4"])

    assert (frames / ".metadata.json").is_file()


def test_an_archive_without_metadata_still_works(tmp_path, monkeypatch):
    """An upload of loose video files has no metadata file"""
    frames = run_extractor(tmp_path, monkeypatch, ["clip.mp4"])

    assert not (frames / ".metadata.json").exists()
    assert (frames / "clip.mp4").is_dir()


"""
The same for scene frames, which has its own extractor.
"""


def run_scene_extractor(tmp_path, monkeypatch, video_names):
    """
    Capture one scene frame per video

    :return Path:  The staging area the folders were written to
    """
    source_archive = tmp_path / "videos.zip"
    with zipfile.ZipFile(source_archive, "w") as archive:
        for filename in video_names:
            archive.writestr(filename, "content")

    videos, scenes = [], []
    for name in video_names:
        video = tmp_path / name
        video.write_text("content")
        videos.append(SimpleNamespace(file=video))
        scenes.append({"id": f"{name}_scene_1", "start_frame": "0", "end_frame": "10"})

    staging_area = tmp_path / "staging"
    staging_area.mkdir()

    monkeypatch.setattr("processors.visualisation.video_scene_frames.shutil.which",
                        lambda path: "/usr/bin/ffmpeg")
    monkeypatch.setattr("processors.visualisation.video_scene_frames.get_ffmpeg_version",
                        lambda path: version.parse("6.0"))
    monkeypatch.setattr("shutil.make_archive", lambda *args, **kwargs: None)

    video_dataset = MagicMock()
    video_dataset.get_results_path.return_value = source_archive
    video_dataset.iterate_items.return_value = videos

    processor = MagicMock()
    processor.parameters = {"frame_size": "no_modify", "key_frame": "first"}
    processor.interrupted = False
    processor.for_cleanup = []
    processor.source_dataset.num_rows = len(scenes)
    processor.source_dataset.iterate_items.return_value = scenes
    processor.source_dataset.nearest.return_value = video_dataset
    processor.dataset.get_staging_area.return_value = staging_area
    processor.dataset.get_results_path.return_value = tmp_path / "results.zip"
    processor.extract_archived_file_by_name = \
        lambda *args: BasicProcessor.extract_archived_file_by_name(processor, *args)

    def fake_ffmpeg(command, **kwargs):
        # ffmpeg writes the file named last on its command line, numbered from 1
        target = pathlib.Path(command[-1].replace("%d", "1"))
        target.write_text("frame")
        return SimpleNamespace(stdout=b"", stderr=b"", returncode=0)

    processor.run_interruptable_process.side_effect = fake_ffmpeg

    VideoSceneFrames.process(processor)
    return staging_area


def test_a_scene_frames_folder_is_named_after_the_video_file(tmp_path, monkeypatch):
    staging_area = run_scene_extractor(tmp_path, monkeypatch, ["clip.mp4"])

    assert [f.name for f in staging_area.iterdir() if f.is_dir()] == ["clip.mp4"]


def test_scene_frames_of_videos_differing_only_in_extension_stay_apart(tmp_path, monkeypatch):
    """
    Each video's frames are numbered from the start, so sharing one folder would
    mean the second video's frames land on the first video's.
    """
    staging_area = run_scene_extractor(tmp_path, monkeypatch, ["clip.mp4", "clip.webm"])

    folders = sorted(f.name for f in staging_area.iterdir() if f.is_dir())
    assert folders == ["clip.mp4", "clip.webm"]
    for folder in folders:
        assert len(list((staging_area / folder).iterdir())) == 1
