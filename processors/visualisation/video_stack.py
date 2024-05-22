"""
Make a stack of videos in a dataset

Creates a video in which multiple videos are layered on top of each other transparently.

This processor also requires ffmpeg to be installed in 4CAT's backend, and
assumes that ffprobe is also present in the same location.
"""
import shutil
import subprocess
import shlex
import re

from packaging import version

from common.config_manager import config
from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.user_input import UserInput
from common.lib.helpers import get_ffmpeg_version

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class VideoStack(BasicProcessor):
    """
    Video stack creator

    Use ffmpeg to render multiple videos into one combined video in which they are overlaid.
    """
    type = "video-stack"  # job type ID
    category = "Visual"  # category
    title = "Stack videos"  # title displayed in UI
    description = "Create a video stack from the videos in the dataset. Videos are layered on top of each other " \
                  "transparently to help visualise similarities. Does not work well with more than a dozen or so " \
                  "videos. Videos are stacked by length, i.e. the longest video is at the 'bottom' of the stack."  # description displayed in UI
    extension = "mp4"  # extension of result file, used internally and in UI

    options = {
        "amount": {
            "type": UserInput.OPTION_TEXT,
            "help": f"Number of videos to stack.",
            "default": 10,
            "max": 50,
            "min": 2,
        },
        "transparency": {
            "type": UserInput.OPTION_TEXT,
            "coerce_tye": float,
            "default": 0.15,
            "min": 0,
            "max": 1,
            "help": "Layer transparency",
            "tooltip": "Transparency of each layer in the stack, between 0 (opaque) and 1 (fully transparent). "
                       "As a rule of thumb, for 10 videos use 90% opacity (0.10), for 20 use 80% (0.20), and so on."
        },
        "eof-action": {
            "type": UserInput.OPTION_CHOICE,
            "options": {
                "pass": "Remove video from stack once it ends",
                "repeat": "Keep displaying final frame until end of stack video",
                "endall": "Stop stack video when first video ends"
            },
            "help": "Length handling",
            "tooltip": "How to handle videos of different length (i.e. when not all videos in the stack are equally "
                       "long)",
            "default": "pass"
        },
        "audio": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Audio handling",
            "options": {
                "longest": "Use audio from longest video in stack",
                "none": "Remove audio"
            },
            "default": "longest"
        }
    }

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Determine compatibility

        :param str module:  Module ID to determine compatibility with
        :return bool:
        """
        # also need ffprobe to determine video lengths
        # is usually installed in same place as ffmpeg
        ffmpeg_path = shutil.which(config.get("video-downloader.ffmpeg_path", user=user))
        ffprobe_path = shutil.which("ffprobe".join(ffmpeg_path.rsplit("ffmpeg", 1))) if ffmpeg_path else None

        return module.type.startswith("video-downloader") and \
               ffmpeg_path and \
               ffprobe_path

    def process(self):
        """
        This takes a zipped set of videos, uses https://pypi.org/project/videohash/ and https://ffmpeg.org/ to collect
        frames from the videos at intervals and create image collages to hashes for comparison of videos.
        """
        # Check processor able to run
        if self.source_dataset.num_rows < 3:
            self.dataset.update_status("Not enough videos to stack (need at least 2)", is_final=True)
            self.dataset.finish(0)
            return

        # Collect parameters
        eof = self.parameters.get("eof-action")
        sound = self.parameters.get("audio")
        amount = self.parameters.get("amount")

        # To figure out the length of a video we use ffprobe, if available
        with_errors = False
        ffmpeg_path = shutil.which(config.get("video-downloader.ffmpeg_path"))
        ffprobe_path = shutil.which("ffprobe".join(ffmpeg_path.rsplit("ffmpeg", 1)))

        # unpack source videos to stack
        video_dataset = self.source_dataset.nearest("video-downloader*")
        if not video_dataset:
            self.log.error(
                f"Trying to extract video data from non-video dataset {video_dataset.key} (type '{video_dataset.type}')")
            return self.dataset.finish_with_error("Video data missing. Cannot stack videos.")

        # a staging area to store the videos we're reading from
        video_staging_area = self.dataset.get_staging_area()

        # determine ffmpeg version
        # -fps_mode is not in older versions and we can use -vsync instead
        # but -vsync will be deprecated so only use it if needed
        # todo: periodically check if we still need to support ffmpeg < 5.1
        # at the time of writing, 4.* is still distributed with various OSes
        fps_params = ["-fps_mode", "vfr"] if get_ffmpeg_version(ffmpeg_path) >= version.parse("5.1") else ["-vsync", "vfr"]

        # command to stack input videos
        transparency_filter = []
        merge_filter = []
        command = [ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error"]
        index = 0
        try:
            transparency = self.parameters.get("transparency", 0.5)
        except ValueError:
            transparency = 0.3

        max_videos = min(amount, self.source_dataset.num_rows - 1)  # minus 1, because .metadata.json
        lengths = {}
        videos = []

        # unpack videos and determine length of the video (for sorting)
        for video in self.iterate_archive_contents(video_dataset.get_results_path(), staging_area=video_staging_area,
                                                   immediately_delete=False):
            if self.interrupted:
                shutil.rmtree(video_staging_area, ignore_errors=True)
                return ProcessorInterruptedException("Interrupted while unpacking videos")

            # skip JSON
            if video.name == '.metadata.json':
                continue

            if len(videos) >= max_videos:
                break

            video_path = shlex.quote(str(video))

            # determine length if needed
            length_command = [ffprobe_path, "-v", "error", "-show_entries", "format=duration", "-of",
                              "default=noprint_wrappers=1:nokey=1", video_path]
            length = subprocess.run(length_command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)

            length_output = length.stdout.decode("utf-8")
            length_error = length.stderr.decode("utf-8")
            if length_error:
                shutil.rmtree(video_staging_area, ignore_errors=True)
                return self.dataset.finish_with_error("Cannot determine length of video {video.name}. Cannot stack "
                                                      "videos without knowing the video lengths.")
            else:
                lengths[video.name] = float(length_output)

            videos.append(video)

        # sort videos by length
        videos = sorted(videos, key=lambda v: lengths[v.name], reverse=True)
        num_videos = len(videos)
        self.dataset.log(f"Collected {num_videos} videos to stack")

        # loop again, this time to construct the ffmpeg command
        last_index = num_videos - 1
        for video in videos:
            video_path = shlex.quote(str(video))
            # video to stack
            command += ["-i", video_path]
            if index > 0:
                # 'bottom' video doesn't need transparency since there's nothing below it
                transparency_filter.append(
                    f"[{index}]format=yuva444p,colorchannelmixer=aa={transparency}[output{index}]")

            overlay = f"overlay=eof_action={eof}"
            if index == 0:
                # first video overlays second video (i.e. the second video w/ transparency filter applied as output1)
                merge_filter.append(f"[0][output1]{overlay}[stage1]")
            elif 0 < index < last_index:
                # each consecutive video overlays the following
                # do this for all but the first one (see above) and the last
                # one (nothing is stacked on top of the last one)
                if index < last_index - 1:
                    merge_filter.append(f"[stage{index}][output{index + 1}]{overlay}[stage{index + 1}]")
                else:
                    # second to last video overlays last video and marks merge filter as final
                    merge_filter.append(f"[stage{index}][output{index + 1}]{overlay}[final]")
            else:
                # last video has no additional overlay
                pass

            index += 1
            self.dataset.update_status(f"Unpacked {index:,} of {num_videos:,} videos")

        # create final complex filter chain
        ffmpeg_filter = shlex.quote(";".join(transparency_filter) + ";" + ";".join(merge_filter))[1:-1]
        command += ["-filter_complex", ffmpeg_filter]

        # ensure mixed audio
        if sound == "none":
            command += ["-an"]
        elif sound == "longest":
            command += ["-map", f"0:a"]

        command += ["-map", "[final]", *fps_params]

        # output file
        command.append(shlex.quote(str(self.dataset.get_results_path())))
        self.dataset.log(f"Using ffmpeg filter {ffmpeg_filter}")

        if self.interrupted:
            shutil.rmtree(video_staging_area, ignore_errors=True)
            return ProcessorInterruptedException("Interrupted while stacking videos")

        self.dataset.update_status("Merging video files with ffmpeg (this can take a while)")
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Capture logs
        ffmpeg_output = result.stdout.decode("utf-8")
        ffmpeg_error = result.stderr.decode("utf-8")

        if ffmpeg_output:
            self.dataset.log("ffmpeg returned the following output:")
            for line in ffmpeg_output.split("\n"):
                self.dataset.log("  " + line)

        if ffmpeg_error:
            self.dataset.log("ffmpeg returned the following errors:")
            for line in ffmpeg_error.split("\n"):
                self.dataset.log("  " + line)

        shutil.rmtree(video_staging_area, ignore_errors=True)

        if result.returncode != 0:
            return self.dataset.finish_with_error(
                f"Could not stack videos (error {result.returncode}); check the dataset log for details.")

        if with_errors:
            self.dataset.update_status("Stack created, but with errors. Check dataset log for details.", is_final=True)

        self.dataset.finish(1)
