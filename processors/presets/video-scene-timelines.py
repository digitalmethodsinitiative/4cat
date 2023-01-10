"""
Create scene-by-scene timelines
"""
import shutil

import common.config_manager as config
from backend.abstract.preset import ProcessorPreset


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
    def is_compatible_with(cls, module=None):
        """
        Determine compatibility

        Compatible with downloaded videos, and not really anything else!
        Additionally ffmpeg needs to be available.

        :param str module:  Module ID to determine compatibility with
        :return bool:
        """
        return module.type in ["video-downloader"] and \
               config.get("video_downloader.ffmpeg-path") and \
               shutil.which(config.get("video_downloader.ffmpeg-path"))

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
