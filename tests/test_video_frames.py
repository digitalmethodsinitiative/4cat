"""
Tests for the frame extractor, which writes a folder of frames per video
"""
import json
import pathlib
import re
import zipfile
from types import SimpleNamespace
from unittest.mock import MagicMock

from packaging import version

from backend.lib.processor import BasicProcessor
from common.lib.helpers import fold_filename
from processors.visualisation.video_frames import VideoFrames
from processors.visualisation.video_scene_frames import VideoSceneFrames


"""
What a video's frames folder is called.

Each video's frames go into their own folder, which keeps a big archive
possible to look through. The folder and the frames in it share one name,
built from the video's name. The extension is part of it, because `clip.mp4`
and `clip.webm` are two videos, and the dot before it becomes an underscore so
a frame is not called `clip.mp4_frame_0000001.jpeg`.

Nothing reads the folders. Which video a frame came from is in the metadata,
as the entry's `source_file`, and no two frames in an archive share a name.
"""

FRAME_TEST_NAMES = ["clip.mp4", "clip.webm", "A.mp4", "a.mp4", "other.mp4"]


def wire_metadata(processor, source_archive, tmp_path):
    """
    Give a mocked processor the two halves of the metadata API it uses.

    Reading comes from the archive the harness actually built, and writing
    produces a real `MediaArchiveMetadata`, so what a processor writes can be
    read back and checked rather than swallowed by a mock.
    """
    from common.lib.archive_metadata import MediaArchiveMetadata
    from common.lib.exceptions import MetadataException

    class Source:
        def get_results_path(self):
            return source_archive

        def is_finished(self):
            return True

        def get_results_folder_path(self):
            return tmp_path / "no-results-folder"

    def read(dataset=None):
        try:
            return MediaArchiveMetadata.read(Source())
        except (FileNotFoundError, MetadataException):
            return None

    processor.get_media_metadata = read
    processor.dataset.new_media_metadata.side_effect = (
        lambda from_dataset, processor_type, filename=".metadata.json": MediaArchiveMetadata.new(
            processor_type=processor_type, from_dataset=from_dataset, filename=filename))


def run_extractor(tmp_path, monkeypatch, video_names, archive_contents=None, metadata=None):
    """
    Extract frames from an archive of videos

    :param dict metadata:  Contents of the archive's `.metadata.json`, if it
      has one; an upload of loose video files does not
    :return Path:  The folder the frames were written to
    """
    source_archive = tmp_path / "videos.zip"
    with zipfile.ZipFile(source_archive, "w") as archive:
        for filename in (archive_contents if archive_contents is not None else video_names):
            archive.writestr(filename, "content")
        if metadata is not None:
            archive.writestr(".metadata.json", json.dumps(metadata))

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
    processor.type = VideoFrames.type
    processor.parameters = {"frame_interval": 1.0, "frame_size": "no_modify"}
    processor.interrupted = False
    processor.source_dataset.key = "videoskey"
    processor.source_dataset.num_rows = len(videos)
    processor.source_dataset.get_results_path.return_value = source_archive
    processor.source_dataset.iterate_items.return_value = videos
    processor.dataset.get_staging_area.return_value = staging_area
    processor.dataset.get_results_path.return_value = tmp_path / "results.zip"
    processor.extract_archived_file_by_name = \
        lambda *args: BasicProcessor.extract_archived_file_by_name(processor, *args)

    def fake_ffmpeg(command, **kwargs):
        # ffmpeg writes the file named last on its command line, numbering the
        # frames of each video from 1
        for number in (1, 2):
            pathlib.Path(command[-1].replace("%07d", "%07d" % number)).write_text("frame")
        return SimpleNamespace(stdout=b"", stderr=b"", returncode=0)

    processor.run_interruptable_process.side_effect = fake_ffmpeg
    wire_metadata(processor, source_archive, tmp_path)

    VideoFrames.process(processor)
    return staging_area / "frames"


def test_a_frames_folder_is_named_after_the_video_file(tmp_path, monkeypatch):
    frames = run_extractor(tmp_path, monkeypatch, ["clip.mp4"])

    assert [folder.name for folder in frames.iterdir() if folder.is_dir()] == ["clip_mp4"]


def test_a_frames_folder_is_named_the_same_as_the_frames_in_it(tmp_path, monkeypatch):
    """One name per video, so the folder cannot drift from what the frames say"""
    frames = run_extractor(tmp_path, monkeypatch, ["clip.mp4"])
    folder = next(item for item in frames.iterdir() if item.is_dir())

    assert all(frame.name.startswith(folder.name + "_") for frame in folder.iterdir())


def test_videos_differing_only_in_extension_get_a_folder_each(tmp_path, monkeypatch):
    frames = run_extractor(tmp_path, monkeypatch, ["clip.mp4", "clip.webm"])

    assert sorted(folder.name for folder in frames.iterdir() if folder.is_dir()) == ["clip_mp4", "clip_webm"]


def test_the_frames_get_metadata_of_their_own(tmp_path, monkeypatch):
    """
    A copy of the videos' metadata is keyed by video, so nothing in it names a
    frame and anything looking a frame up finds nothing. Each frame gets its
    own entry instead, carrying the posts its video was downloaded for.
    """
    frames = run_extractor(tmp_path, monkeypatch, ["clip.mp4"], metadata={
        "https://example.test/clip": {"success": True, "post_ids": ["p1", "p2"],
                                      "files": [{"filename": "clip.mp4", "success": True}]},
    })

    assert (frames / ".metadata.json").is_file()
    written = json.loads((frames / ".metadata.json").read_text(encoding="utf-8"))

    assert written["schema_version"] == 1
    assert written["processor_type"] == "video-frames"

    # keyed by each frame's name, not by its path in the archive. Everything
    # that reads a media archive looks a file up by `item.file.name`, so a
    # path would be a key nothing asks for. The names are unique archive-wide,
    # which is what lets the folders stay out of it.
    assert sorted(written["items"]) == ["clip_mp4_frame_0000001.jpeg",
                                        "clip_mp4_frame_0000002.jpeg"]
    for entry in written["items"].values():
        assert entry["post_ids"] == ["p1", "p2"]
        assert entry["source_file"] == "clip.mp4"

    # and a consumer can get from a post back to the frames it produced, which
    # is the whole point of writing this
    from common.lib.archive_metadata import MediaArchiveMetadata

    class Written:
        def get_results_path(self):
            return frames / ".metadata.json"

        def is_finished(self):
            return True

        def get_results_folder_path(self):
            return frames

    assert MediaArchiveMetadata.read(Written()).post_id_to_filenames()["p1"] == [
        "clip_mp4_frame_0000001.jpeg", "clip_mp4_frame_0000002.jpeg"]


def test_an_archive_without_metadata_still_works(tmp_path, monkeypatch):
    """
    An upload of loose video files has no metadata, so the frames know no posts
    - but which video each came from is worth recording either way.
    """
    frames = run_extractor(tmp_path, monkeypatch, ["clip.mp4"])

    assert (frames / "clip_mp4").is_dir()
    written = json.loads((frames / ".metadata.json").read_text(encoding="utf-8"))
    entry = written["items"]["clip_mp4_frame_0000001.jpeg"]
    assert entry["post_ids"] == []
    assert entry["source_file"] == "clip.mp4"


"""
Whether two frames can be given the same name.

The folder a frame is in is what ties it to its video, but not everything that
reads the frames keeps the folders. The image wall holds the files it is about
to draw in a dictionary by name, and the unique image filter copies them all
into a single folder. A name that two frames share is then one frame, and the
other is gone without a word. So no two frames in an archive may be called the
same thing, whichever videos they were taken from.

Names that differ only in their capitals are two names to Linux and one name
to Windows and macOS. 4CAT writes the archive on the server, but the
researcher unpacks it on their own machine, so such a pair loses a frame there
while the server sees nothing wrong. Both kinds are checked here, apart from
one another, because a server running Linux can only ever notice the first.
"""


def shared_names(folder):
    """
    The file names in `folder` that more than one file has

    The second kind is judged with `fold_filename`, the same way the code that
    hands names out judges it, so a name this accepts is a name that can be
    written. Capitals are only one of the differences it covers.

    :param Path folder:  Folder to look through, including its subfolders
    :return tuple:  (names that more than one file has, names that are one
      name to Windows or macOS)
    """
    names = [file.name for file in folder.rglob("*") if file.is_file()]
    folded = [fold_filename(name) for name in names]
    same = sorted({name for name in names if names.count(name) > 1})
    same_elsewhere = sorted({name for name in names
                             if folded.count(fold_filename(name)) > 1 and name not in same})
    return same, same_elsewhere


def test_no_two_frames_are_given_the_same_name(tmp_path, monkeypatch):
    frames = run_extractor(tmp_path, monkeypatch, FRAME_TEST_NAMES)

    same, _ = shared_names(frames)
    assert not same, f"frames of different videos were given these names: {same}"


def test_no_two_frames_are_one_name_on_windows_or_macos(tmp_path, monkeypatch):
    frames = run_extractor(tmp_path, monkeypatch, FRAME_TEST_NAMES)

    _, same_elsewhere = shared_names(frames)
    assert not same_elsewhere, ("unpacking the archive on Windows or macOS would lose one of "
                                f"each of these: {same_elsewhere}")


"""
The same for scene frames, which has its own extractor.
"""


def run_scene_extractor(tmp_path, monkeypatch, video_names, scenes_per_video=1, frames_written=None,
                        frame_size="no_modify", reverse_scenes=False):
    """
    Capture a frame per scene of each video

    Scene `n` of a video starts at frame `n * 10`, so a frame holding
    `video frame 30` is the one scene 3 asked for.

    :param int scenes_per_video:  How many scenes each video is said to have
    :param int frames_written:  How many frames ffmpeg writes, which is one
      per scene unless a test is about it writing fewer
    :param str frame_size:  The size to resize the frames to, if any
    :param bool reverse_scenes:  Hand the scenes over last-first, for a test
      about not relying on the order they arrive in
    :return tuple:  The staging area the folders were written to, and the
      processor, whose mock records what was logged and what ffmpeg was asked
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
        of_this_video = [{"id": f"{name}_scene_{number}",
                          "start_frame": str(number * 10), "end_frame": str(number * 10 + 10)}
                         for number in range(1, scenes_per_video + 1)]
        scenes.extend(reversed(of_this_video) if reverse_scenes else of_this_video)

    staging_area = tmp_path / "staging"
    staging_area.mkdir()

    monkeypatch.setattr("processors.visualisation.video_scene_frames.shutil.which",
                        lambda path: "/usr/bin/ffmpeg")
    monkeypatch.setattr("processors.visualisation.video_scene_frames.get_ffmpeg_version",
                        lambda path: version.parse("6.0"))
    monkeypatch.setattr("shutil.make_archive", lambda *args, **kwargs: None)

    video_dataset = MagicMock()
    video_dataset.key = "videoskey"
    video_dataset.get_results_path.return_value = source_archive
    video_dataset.iterate_items.return_value = videos

    processor = MagicMock()
    processor.type = VideoSceneFrames.type
    processor.parameters = {"frame_size": frame_size, "key_frame": "first"}
    processor.interrupted = False
    processor.for_cleanup = []
    processor.source_dataset.num_rows = len(scenes)
    processor.source_dataset.iterate_items.return_value = scenes
    processor.source_dataset.nearest.return_value = video_dataset
    processor.dataset.get_staging_area.return_value = staging_area
    processor.dataset.get_results_path.return_value = tmp_path / "results.zip"
    processor.extract_archived_file_by_name = \
        lambda *args: BasicProcessor.extract_archived_file_by_name(processor, *args)

    emitted = scenes_per_video if frames_written is None else frames_written

    def fake_ffmpeg(command, **kwargs):
        # ffmpeg reads the video once and saves the frames it was asked for as
        # it reaches them, so they come out in video order whatever order they
        # were asked in, numbered from 1. Each file holds the video frame it
        # came from, so a test can see which scene it was named after.
        select = next(argument for argument in command if argument.startswith("select="))
        wanted = sorted(int(number) for number in re.findall(r"eq\(n\\,(\d+)\)", select))
        for position, source_frame in enumerate(wanted[:emitted], start=1):
            pathlib.Path(command[-1].replace("%07d", "%07d" % position)).write_text(
                f"video frame {source_frame}")
        return SimpleNamespace(stdout=b"", stderr=b"", returncode=0)

    processor.run_interruptable_process.side_effect = fake_ffmpeg
    wire_metadata(processor, source_archive, tmp_path)

    VideoSceneFrames.process(processor)
    return staging_area, processor


def test_a_scene_frames_folder_is_named_after_the_video_file(tmp_path, monkeypatch):
    staging_area, _ = run_scene_extractor(tmp_path, monkeypatch, ["clip.mp4"])

    assert [f.name for f in staging_area.iterdir() if f.is_dir()] == ["clip_mp4"]


def test_scene_frames_of_videos_differing_only_in_extension_stay_apart(tmp_path, monkeypatch):
    """
    Each video's frames are numbered from the start, so sharing one folder would
    mean the second video's frames land on the first video's.
    """
    staging_area, _ = run_scene_extractor(tmp_path, monkeypatch, ["clip.mp4", "clip.webm"])

    folders = sorted(f.name for f in staging_area.iterdir() if f.is_dir())
    assert folders == ["clip_mp4", "clip_webm"]
    for folder in folders:
        assert len(list((staging_area / folder).iterdir())) == 1


def test_no_two_scene_frames_are_given_the_same_name(tmp_path, monkeypatch):
    """Two videos whose names differ only in the extension share a name for their frames"""
    staging_area, _ = run_scene_extractor(tmp_path, monkeypatch, FRAME_TEST_NAMES)

    same, _ = shared_names(staging_area)
    assert not same, f"scene frames of different videos were given these names: {same}"


def test_no_two_scene_frames_are_one_name_on_windows_or_macos(tmp_path, monkeypatch):
    """Two videos whose names differ only in their capitals are one video to Windows and macOS"""
    staging_area, _ = run_scene_extractor(tmp_path, monkeypatch, FRAME_TEST_NAMES)

    _, same_elsewhere = shared_names(staging_area)
    assert not same_elsewhere, ("unpacking the archive on Windows or macOS would lose one of "
                                f"each of these: {same_elsewhere}")


"""
Which scene a frame is named after.

ffmpeg numbers the frames it saves from 1, in the order they appear in the
video. The frames are read back in that order and matched with the scenes
sorted the same way. If ffmpeg saved fewer frames than there are scenes, the
match cannot be trusted and the dataset says so.
"""


def test_scene_frames_are_paired_with_scenes_in_ffmpeg_s_own_order(tmp_path, monkeypatch):
    """
    More than nine frames, so the order matters: as text `_frame_10` comes
    before `_frame_2`, and pairing them that way would name almost every frame
    after the wrong scene.
    """
    staging_area, _ = run_scene_extractor(tmp_path, monkeypatch, ["clip.mp4"], scenes_per_video=11)
    folder = staging_area / "clip_mp4"

    for number in range(1, 12):
        assert (folder / f"clip_mp4_scene_{number}.jpeg").read_text() == f"video frame {number * 10}"


def test_scenes_that_arrive_out_of_order_still_get_their_own_frames(tmp_path, monkeypatch):
    """
    The scenes need not arrive in the order they appear in the video, but
    ffmpeg always saves its frames in that order, so the scenes are sorted
    before being matched with them.
    """
    staging_area, _ = run_scene_extractor(tmp_path, monkeypatch, ["clip.mp4"],
                                          scenes_per_video=4, reverse_scenes=True)
    folder = staging_area / "clip_mp4"

    for number in range(1, 5):
        assert (folder / f"clip_mp4_scene_{number}.jpeg").read_text() == f"video frame {number * 10}"


def test_fewer_frames_than_scenes_is_reported(tmp_path, monkeypatch):
    """
    A missing frame would move every frame after it onto the wrong scene, and
    the files do not say which scene is missing, so the dataset gets a warning.
    """
    staging_area, processor = run_scene_extractor(tmp_path, monkeypatch, ["clip.mp4"],
                                                  scenes_per_video=3, frames_written=2)

    logged = " ".join(str(call) for call in processor.dataset.log.call_args_list)
    assert "3 frame(s) of clip.mp4 but it wrote 2" in logged
    assert processor.dataset.finish_with_warning.called

    # and the frames it did write are still named, kept and traceable
    kept = sorted(path.name for path in (staging_area / "clip_mp4").iterdir())
    assert kept == ["clip_mp4_scene_1.jpeg", "clip_mp4_scene_2.jpeg"]


def test_the_frame_size_option_comes_before_the_output_file(tmp_path, monkeypatch):
    """
    ffmpeg options for a file go before that file's name. After it, `-s`
    belongs to an output that never comes and ffmpeg saves nothing.
    """
    _, processor = run_scene_extractor(tmp_path, monkeypatch, ["clip.mp4"], frame_size="144x144")
    command = processor.run_interruptable_process.call_args_list[0][0][0]

    assert command[-1].endswith(".jpeg"), f"the output file should come last: {command}"
    assert "-s" in command[:-1], f"the frame size should come before the output file: {command}"
