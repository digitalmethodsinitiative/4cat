"""
Get first frame of each scene identified in a set of videos

Similar to 'Extract frames', but different enough that it gets its own file.

This processor also requires ffmpeg to be installed in 4CAT's backend
https://ffmpeg.org/
"""
import shutil
import subprocess
import shlex

from packaging import version

from common.config_manager import config
from backend.lib.processor import BasicProcessor
from common.lib.user_input import UserInput
from common.lib.helpers import get_ffmpeg_version

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class VideoSceneFrames(BasicProcessor):
    """
    Video Frame Extracter

    Uses ffmpeg to extract a certain number of frames per second at different sizes and saves them in an archive.
    """
    type = "video-scene-frames"  # job type ID
    category = "Visual"  # category
    title = "Extract first frames from each scene"  # title displayed in UI
    description = "For each scene identified, extracts the first frame."  # description displayed in UI
    extension = "zip"  # extension of result file, used internally and in UI

    options = {
        "frame_size": {
            "type": UserInput.OPTION_CHOICE,
            "default": "medium",
            "options": {
                "no_modify": "Do not modify",
                "144x144": "Tiny (144x144)",
                "432x432": "Medium (432x432)",
                "1026x1026": "Large (1026x1026)",
            },
            "help": "Size of extracted frames"
        },
    }

    followups = ["video-timelines"]

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Determine compatibility

        Compatible with scene data only.

        :param str module:  Module ID to determine compatibility with
        :return bool:
        """
        return module.type in ["video-scene-detector"] and \
               config.get("video-downloader.ffmpeg_path") and \
               shutil.which(config.get("video-downloader.ffmpeg_path"))

    def process(self):
        """
        This takes a zipped set of videos, uses https://pypi.org/project/videohash/ and https://ffmpeg.org/ to collect
        frames from the videos at intervals and create image collages to hashes for comparison of videos.
        """
        # Check processor able to run
        if self.source_dataset.num_rows == 0:
            self.dataset.update_status("No videos from which to extract frames.", is_final=True)
            self.dataset.finish(0)
            return

        # Collect parameters
        frame_size = self.parameters.get("frame_size", "no_modify")

        # unpack source videos to get frames from
        video_dataset = self.source_dataset.nearest("video-downloader*")
        if not video_dataset:
            self.log.error(
                f"Trying to extract video data from non-video dataset {video_dataset.key} (type '{video_dataset.type}')")
            return self.dataset.finish_with_error("Video data missing for scene metadata. Cannot extract frames.")

        # map scenes to filenames
        scenes = {}
        for scene in self.source_dataset.iterate_items(self):
            filename = "_scene_".join(scene["id"].split("_scene_")[:-1])
            if filename not in scenes:
                scenes[filename] = []
            scenes[filename].append(scene)

        # two separate staging areas:
        # one to store the videos we're reading from
        # one to store the frames we're capturing
        video_staging_area = self.dataset.get_staging_area()
        staging_area = self.dataset.get_staging_area()

        errors = 0
        processed_frames = 0
        num_scenes = self.source_dataset.num_rows
        for video in self.iterate_archive_contents(video_dataset.get_results_path(), staging_area=video_staging_area):
            # Check for 4CAT's metadata JSON and copy it
            if video.name == '.metadata.json':
                shutil.copy(video, staging_area)

            if video.name not in scenes:
                continue

            video_folder = staging_area.joinpath(video.stem)
            video_folder.mkdir(exist_ok=True)

            ffmpeg_path = shutil.which(self.config.get("video-downloader.ffmpeg_path"))
            fps_command = "-fps_mode" if get_ffmpeg_version(ffmpeg_path) >= version.parse("5.1") else "-vsync"

            # we use a single command per video and get all frames in one go
            # previously we had a separate command per frame, which is slower
            frames = [s["start_frame"] for s in scenes[video.name]]
            vf_param = "+".join([f"eq(n\\,{frame})" for frame in frames])

            command = [
                ffmpeg_path,
                "-i", shlex.quote(str(video)),
                "-vf", f"select='{vf_param}'",
                fps_command, "passthrough",
                shlex.quote(str(video_folder.joinpath(f"{video.stem}_frame_%d.jpeg")))
            ]

            if frame_size != "no_modify":
                command += ["-s", shlex.quote(frame_size)]

            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)

            # some ffmpeg error - log but continue
            if result.returncode != 0:
                self.dataset.log(
                    f"Error extracting frames for video file {video.name}, skipping.")

                errors += 1

            # the default filenames can be improved - use scene ID instead of frame #
            for i in range(0, len(scenes[video.name])):
                frame_file = video_folder.joinpath(f"{video.stem}_frame_{i+1}.jpeg")
                scene_id = scenes[video.name][i]["id"].split("_").pop()
                frame_file.rename(frame_file.with_stem(f"{video.stem}_scene_{scene_id}"))

            processed_frames += len(scenes[video.name])

            self.dataset.update_status(f"Captured frames for {processed_frames:,} of {num_scenes:,} scenes")
            self.dataset.update_progress(processed_frames / num_scenes)

        # Finish up
        # We've created a directory and folder structure here as opposed to a single folder with single files as
        # expected by self.write_archive_and_finish() so we use make_archive instead
        from shutil import make_archive
        make_archive(self.dataset.get_results_path().with_suffix(''), "zip", staging_area)

        if errors:
            self.dataset.update_status("Finished, but not all scenes could be captured. See dataset log for "
                                       "details.", is_final=True)

        # Remove staging areas
        shutil.rmtree(staging_area)
        shutil.rmtree(video_staging_area)

        self.dataset.finish(processed_frames)
