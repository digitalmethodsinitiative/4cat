"""
Get first frame of each scene identified in a set of videos

Similar to 'Extract frames', but different enough that it gets its own file.

This processor also requires ffmpeg to be installed in 4CAT's backend
https://ffmpeg.org/
"""
import shutil
import oslex

from packaging import version

from backend.lib.processor import BasicProcessor, ProcessorDescription
from common.lib.compatibility import Compatibility, is_executable
from common.lib.outputs import MediaArchive
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
    description = ProcessorDescription(
        title="Extract key frames from each scene",
        category="Visual",
        tags=["extract"],
        description="Extract one key frame from each detected scene and save the frames as an image archive. Choose the first, middle, or last frame of each scene, optionally resized to a fixed size.",
        info=[
            "Follow up with 'Create video timelines' to arrange the extracted frames into a visual overview.",
        ],
        icon="photo-film",
    )
    extension = "zip"  # extension of result file, used internally and in UI
    media_type = "image"  # the extracted frames are images; set so the map and runtime agree
    # a zip archive of image files
    output = MediaArchive(media="image")

    # Allow on detected video scenes when ffmpeg is available
    compatibility = Compatibility(types={"video-scene-detector"}, required_settings={("video-downloader.ffmpeg_path", is_executable)}, preferred_followups=["video-timelines"])

    @classmethod
    def get_options(cls, parent_dataset=None, config=None) -> dict:
        """
        Get processor options

        :param parent_dataset DataSet:  An object representing the dataset that
            the processor would be or was run on. Can be used, in conjunction with
            config, to show some options only to privileged users.
        :param config ConfigManager|None config:  Configuration reader (context-aware)
        :return dict:   Options for this processor
        """
        return {
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
            "key_frame": {
                "type": UserInput.OPTION_CHOICE,
                "default": "first",
                "help": "Key frame",
                "options": {
                    "first": "First frame",
                    "middle": "Middle frame",
                    "last": "Last frame"
                },
                "tooltip": "Which scene to select from each frame. Note that scene boundaries are determined by the "
                        "difference between the last frame of the previous scene, and the first frame of the next."
            }
        }

    def process(self):
        """
        This takes a zipped set of videos, uses https://pypi.org/project/videohash/ and https://ffmpeg.org/ to collect
        frames from the videos at intervals and create image collages to hashes for comparison of videos.
        """
        # Check processor able to run
        if self.source_dataset.num_rows == 0:
            self.dataset.finish_as_empty("No videos from which to extract frames.")
            return

        # Collect parameters
        frame_size = self.parameters.get("frame_size", "no_modify")
        key_frame = self.parameters.get("key_frame", "first")

        # unpack source videos to get frames from
        video_dataset = None
        for video_dataset_type in ["video-downloader*", "media-import-search"]:
            if video_dataset is None:
                video_dataset = self.source_dataset.nearest(video_dataset_type)
        if not video_dataset:
            self.log.error(
                f"Trying to extract video data from non-video dataset {video_dataset.key} (type '{video_dataset.type}')")
            return self.dataset.finish_with_error("Video data missing for scene metadata. Cannot extract frames.")

        self.for_cleanup.append(video_dataset)

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
        staging_area = self.dataset.get_staging_area()

        errors = 0
        processed_frames = 0
        num_scenes = self.source_dataset.num_rows
        for video in video_dataset.iterate_items(self):
            # Check for 4CAT's metadata JSON and copy it
            if video.file.name == '.metadata.json':
                shutil.copy(video.file, staging_area)

            if video.file.name not in scenes:
                continue

            self.dataset.log(f"Video {video.file.name} has {len(scenes[video.file.name]):,} scenes")

            video_folder = staging_area.joinpath(video.file.stem)
            video_folder.mkdir(exist_ok=True)

            ffmpeg_path = shutil.which(self.config.get("video-downloader.ffmpeg_path"))
            fps_command = "-fps_mode" if get_ffmpeg_version(ffmpeg_path) >= version.parse("5.1") else "-vsync"

            # we use a single command per video and get all frames in one go
            # previously we had a separate command per frame, which is slower
            # which frame? depends on the key frame setting - for 'middle' we
            # need to do some calculations
            keyframe_field = {"first": "start_frame", "last": "end_frame", "middle": None}.get(key_frame)
            frame_scenes = []
            for scene in scenes[video.file.name]:
                bounds = {k: int(v) for k, v in scene.items() if k.endswith("_frame")}
                frame_scenes.append({
                    "scene": scene["id"].split("_").pop(),
                    "frame": scene.get(keyframe_field) if keyframe_field else int(
                        bounds["start_frame"] + ((bounds["end_frame"] - bounds["start_frame"]) / 2)
                    )
                })

            vf_param = "+".join([f"eq(n\\,{frame['frame']})" for frame in frame_scenes])

            command = [
                ffmpeg_path,
                "-i", oslex.quote(str(video.file)),
                "-vf", f"select='{vf_param}'",
                fps_command, "passthrough",
                oslex.quote(str(video_folder.joinpath(f"{video.file.stem}_frame_%d.jpeg")))
            ]

            if frame_size != "no_modify":
                command += ["-s", oslex.quote(frame_size)]

            result = self.run_interruptable_process(command, cleanup_paths=(staging_area,))

            # some ffmpeg error - log but continue
            if result.returncode != 0:
                self.dataset.log(
                    f"Error extracting frames for video file {video.file.name}, skipping.")

                errors += 1

            # the default filenames can be improved - use scene ID instead of frame #
            for i in range(0, len(scenes[video.file.name])):
                frame_file = video_folder.joinpath(f"{video.file.stem}_frame_{i+1}.jpeg")
                frame_file.rename(frame_file.with_stem(f"{video.file.stem}_scene_{frame_scenes[i]['scene']}"))

            processed_frames += len(scenes[video.file.name])

            self.dataset.update_status(f"Captured frames for {processed_frames:,} of {num_scenes:,} scenes")
            self.dataset.update_progress(processed_frames / num_scenes)

        # Finish up
        # We've created a directory and folder structure here as opposed to a single folder with single files as
        # expected by self.write_archive_and_finish() so we use make_archive instead
        from shutil import make_archive
        make_archive(self.dataset.get_results_path().with_suffix(''), "zip", staging_area)

        if errors:
            warning = "Not all scenes could be captured. See dataset log for details."
            self.dataset.finish_with_warning(processed_frames, warning=warning)
        else:
            self.dataset.finish(processed_frames)
