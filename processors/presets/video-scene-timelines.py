"""
Create scene-by-scene timelines
"""
import shutil

from common.config_manager import config
from backend.lib.preset import ProcessorPreset


class VideoSceneTimelineCreator(ProcessorPreset):
    """
    Run processor pipeline to create video scene timelines
    """
    type = "preset-scene-timelines"  # job type ID
    category = "Visual"  # category. 'Combined processors' are always listed first in the UI.
    title = "Create scene-by-scene timelines"  # title displayed in UI
    description = "Creates a 'timeline' for each video, a horizontal collage of sequential frames. Each 'scene' in " \
                  "the video is visualised as a single frame. Scenes are detected algorithmically. The timelines " \
                  "for all videos are then stacked vertically and rendered as a single SVG file."
    extension = "svg"

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Determine compatibility

        Compatible with downloaded videos, and not really anything else!
        Additionally ffmpeg needs to be available.

        :param str module:  Module ID to determine compatibility with
        :return bool:
        """
        return module.type.startswith("video-downloader") and \
               config.get("video-downloader.ffmpeg_path", user=user) and \
               shutil.which(config.get("video-downloader.ffmpeg_path"))

    def get_processor_pipeline(self):
        """
        This queues a series of post-processors to visualise videos.
        """

        pipeline = [
            # first, detect scenes (with the default settings)
            {
                "type": "video-scene-detector"
            },
            # then, extract frames per scene
            {
                "type": "video-scene-frames"
            },
            # and finally, render to a combined collage
            {
                "type": "video-timelines"
            }
        ]

        return pipeline
