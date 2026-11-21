"""
Get first frame of each scene identified in a set of videos

Similar to 'Extract frames', but different enough that it gets its own file.

This processor also requires ffmpeg to be installed in 4CAT's backend
https://ffmpeg.org/
"""
import shutil
import oslex

from packaging import version

from backend.lib.processor import BasicProcessor
from common.lib.compatibility import Compatibility, is_executable
from common.lib.user_input import UserInput
from common.lib.helpers import get_ffmpeg_version, UniqueFilenames

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
    title = "Extract key frames from each scene"  # title displayed in UI
    description = "For each scene identified, extracts a key frame (e.g. the first frame)."  # description displayed in UI
    extension = "zip"  # extension of result file, used internally and in UI
    media_type = "image"

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
        # scenes looked at, which is what the progress bar counts, and frames
        # actually written, which is what the dataset ends up holding. track
        # to report as we lose which scene each frame belongs to if they differ.
        processed_frames = 0
        captured_frames = 0
        unmatched_videos = 0
        num_scenes = self.source_dataset.num_rows


        # create metadata file so frames can be traced back to original videos/posts
        source_metadata = self.get_media_metadata(video_dataset)
        metadata = self.dataset.new_media_metadata(
            processor_type=self.type,
            from_dataset=((source_metadata.from_dataset if source_metadata else None)
                          or video_dataset.key),
        )

        # one name per video (folder) and frames. frames are named after the
        # video. No two frames in the archive can share a name: processors
        # loops through all files and ignore folders (better to rely on metadata).
        # The folders keep the frames tidy, but metadata stores `source_file`.
        # UniqueFilenames ensures that the names are unique, even if two videos have
        # or would have the same name (include extension for "clip.mp4" and "clip.webm").
        frame_names = UniqueFilenames(staging_area)

        # figure out the longest suffix that will be added to a frame name, so we can reserve enough space.
        # the number is padded so the frames sort in the order ffmpeg saved them
        frame_pattern = "_frame_%07d.jpeg"
        scene_pattern = "_scene_%s.jpeg"
        longest_name_added = max(frame_pattern % 10 ** 10, scene_pattern % 10 ** 10, key=len)

        for video in video_dataset.iterate_items(self):
            if video.file.name not in scenes:
                continue

            self.dataset.log(f"Video {video.file.name} has {len(scenes[video.file.name]):,} scenes")

            # every video numbers its frames from 1, so the video's name is what
            # tells one video's first frame from another's
            frame_name = frame_names.reserve_prefix(video.file.name, adds=longest_name_added)
            video_folder = staging_area.joinpath(frame_name)
            video_folder.mkdir()

            ffmpeg_path = shutil.which(self.config.get("video-downloader.ffmpeg_path"))
            fps_command = "-fps_mode" if get_ffmpeg_version(ffmpeg_path) >= version.parse("5.1") else "-vsync"

            # we use a single command per video and get all frames in one go
            # previously we had a separate command per frame, which is slower
            # which frame? depends on the key frame setting - for 'middle' we
            # need to do some calculations
            keyframe_field = {"first": "start_frame", "last": "end_frame", "middle": None}.get(key_frame)
            # which scenes want each frame of the video. Two scenes could name
            # the same frame if the detector shortens the last scene of a video
            # to end on a frame that is already used by another scene or a scene
            # is a frame long (ffmpeg saves a only once).
            scenes_by_frame = {}
            for scene in scenes[video.file.name]:
                # from `bounds`, which has these as numbers; the scene dataset
                # stores them as text
                bounds = {k: int(v) for k, v in scene.items() if k.endswith("_frame")}
                frame = bounds[keyframe_field] if keyframe_field else int(
                    bounds["start_frame"] + ((bounds["end_frame"] - bounds["start_frame"]) / 2)
                )
                scenes_by_frame.setdefault(frame, []).append(scene["id"].split("_").pop())

            # ffmpeg saves the frames in the order they appear in the video,
            # so ask for them in that order and they come back in it
            wanted_frames = sorted(scenes_by_frame)

            vf_param = "+".join([f"eq(n\\,{frame})" for frame in wanted_frames])

            command = [
                ffmpeg_path,
                "-i", oslex.quote(str(video.file)),
                "-vf", f"select='{vf_param}'",
                fps_command, "passthrough",
            ]

            # ffmpeg options for a file go before that file's name
            if frame_size != "no_modify":
                command += ["-s", oslex.quote(frame_size)]

            command.append(oslex.quote(str(video_folder.joinpath(f"{frame_name}{frame_pattern}"))))

            result = self.run_interruptable_process(command, cleanup_paths=(staging_area,))

            # some ffmpeg error - log but continue
            if result.returncode != 0:
                self.dataset.log(
                    f"Error extracting frames for video file {video.file.name}, skipping.")

                errors += 1

            # every frame stands for the items the video did, and says which
            # scene it was taken from
            video_item = source_metadata.get_entry(video.file.name) if source_metadata else None
            post_ids = video_item.get("post_ids", []) if video_item else []
            source_url = video_item.get("url") if video_item else None

            # the frames ffmpeg saved, in the order it saved them. This folder
            # holds nothing else yet, so reading it is simpler than working
            # out the names ffmpeg gave them
            written = sorted(video_folder.glob("*.jpeg"))

            if len(written) == len(wanted_frames):
                # use scene ID for the default filenames
                for frame_file, frame in zip(written, wanted_frames):
                    scene_frames = [video_folder.joinpath(f"{frame_name}{scene_pattern % scene}")
                                    for scene in scenes_by_frame[frame]]
                    # the file is renamed for the first scene that named this
                    # frame and copied for the others, so each scene has an
                    # image of its own
                    frame_file.rename(scene_frames[0])
                    for scene_frame in scene_frames[1:]:
                        shutil.copy2(scene_frames[0], scene_frame)

                    for scene, scene_frame in zip(scenes_by_frame[frame], scene_frames):
                        metadata.add_item(scene_frame.name, post_ids=post_ids, url=source_url,
                                          source_file=video.file.name,
                                          extra={"scene": scene})
                        captured_frames += 1
            elif not written:
                # nothing to name or keep, so the posts are recorded as having
                # got no frame at all
                errors += 1
                metadata.add_failure(
                    post_ids=post_ids, url=source_url, source_file=video.file.name,
                    reason="no_frames_extracted",
                    reason_description=(f"ffmpeg exited with code {result.returncode}" if result.returncode
                                        else "ffmpeg reported no error but wrote no frames"))
            else:
                # We ended up with too many frames or not enough.
                # And we cannot tell which frames were missed (ffmpeg numbers
                # the frames it saves from 1 but that doesn't tell us which frame
                # of the video it represents)
                # They are still in the order they appear in the video though,
                # so we only lose the scene the frame is from
                errors += 1
                unmatched_videos += 1
                self.dataset.log(
                    f"Asked ffmpeg for {len(wanted_frames):,} frame(s) of {video.file.name} but it wrote "
                    f"{len(written):,}, so which scene each frame belongs to cannot be established; "
                    f"keeping them in the order ffmpeg saved them, without a scene")
                for frame_file in written:
                    metadata.add_item(frame_file.name, post_ids=post_ids, url=source_url,
                                      source_file=video.file.name)
                    captured_frames += 1

            processed_frames += len(scenes[video.file.name])

            self.dataset.update_status(f"Captured frames for {processed_frames:,} of {num_scenes:,} scenes")
            self.dataset.update_progress(processed_frames / num_scenes)

        # Finish up
        if not captured_frames:
            self.dataset.finish_with_error(
                "ffmpeg captured no frames for any of the videos. See the dataset log for details.")
            return

        # We've created a directory and folder structure here as opposed to a single folder with single files as
        # expected by self.write_archive_and_finish() so we use make_archive instead
        metadata.write(staging_area)

        from shutil import make_archive
        make_archive(self.dataset.get_results_path().with_suffix(''), "zip", staging_area)

        if errors:
            warning = (f"The frames of {unmatched_videos:,} video(s) could not be matched to their scenes, so they "
                       f"are named and recorded without one. See the dataset log for details."
                       if unmatched_videos else "Not all scenes could be captured. See dataset log for details.")
            self.dataset.finish_with_warning(captured_frames, warning=warning)
        else:
            self.dataset.finish(captured_frames)
