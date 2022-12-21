"""
Get first frame of each scene identified in a set of videos

Similar to 'Extract frames', but different enough that it gets its own file.

This processor also requires ffmpeg to be installed in 4CAT's backend
https://ffmpeg.org/
"""
import shutil
import subprocess
import shlex

import common.config_manager as config

from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.user_input import UserInput

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
    def is_compatible_with(cls, module=None):
        """
        Determine compatibility

        Compatible with scene data only.

        :param str module:  Module ID to determine compatibility with
        :return bool:
        """
        return module.type in ["video-scene-detector"] and \
               config.get("video_downloader.ffmpeg-path") and \
               shutil.which(config.get("video_downloader.ffmpeg-path"))

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
        video_dataset = self.source_dataset.nearest("video-downloader")
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
        video_staging_area = video_dataset.get_staging_area()
        staging_area = self.dataset.get_staging_area()

        # now go through videos and get the relevant frames
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

            for scene in scenes[video.name]:
                scene_index = scene["id"].split("_").pop()
                scene_filename = video.stem + "_scene_" + str(scene_index) + ".jpeg"
                command = [
                    shutil.which(config.get("video_downloader.ffmpeg-path")),
                    "-i", shlex.quote(str(video)),
                    "-vf", "select='eq(n\\," + scene["start_frame"] + ")'",
                    "-vframes", "1",
                    shlex.quote(str(video_folder.joinpath(scene_filename)))
                ]

                if frame_size != "no_modify":
                    command += ["-s", shlex.quote(frame_size)]

                result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE)

                # some ffmpeg error - log but continue
                if result.returncode != 0:
                    self.dataset.log(
                        f"Error extracting frame for scene {scene_index} of video file {video.name}, skipping.")
                    print(result.stderr)
                    errors += 1

                processed_frames += 1

            self.dataset.update_status(f"Captured frames for {processed_frames} of {num_scenes} scenes")
            self.dataset.update_progress(processed_frames / self.source_dataset.num_rows)

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
