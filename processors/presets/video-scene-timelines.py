"""
Create scene-by-scene timelines
"""

from backend.lib.preset import ProcessorPreset
from common.lib.compatibility import Compatibility, is_executable
from common.lib.outputs import Delegated


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
    icon = "film"

    # a preset; its output is its last step's
    output = Delegated()

    # Allow on video datasets when ffmpeg is available
    compatibility = Compatibility(extension={"zip"},media_types={"video"}, type_prefixes={"video-downloader"}, required_settings={("video-downloader.ffmpeg_path", is_executable)})

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
