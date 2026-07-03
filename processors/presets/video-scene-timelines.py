"""
Create scene-by-scene timelines
"""

from backend.lib.preset import ProcessorPreset
from backend.lib.processor import ProcessorDescription
from common.lib.compatibility import Compatibility, is_executable
from common.lib.outputs import Delegated


class VideoSceneTimelineCreator(ProcessorPreset):
    """
    Run processor pipeline to create video scene timelines
    """
    type = "preset-scene-timelines"  # job type ID
    description = ProcessorDescription(
        title="Create scene-by-scene timelines",
        category="Visual",
        tags=["needs ffmpeg"],
        description="Build a horizontal timeline for each video, showing one frame per detected scene. Scenes are detected automatically, and the per-video timelines are stacked into a single SVG file.",
        icon="film",
    )
    extension = "svg"

    # a preset; its output is its last step's
    output = Delegated()

    # Allow on video datasets when ffmpeg is available
    compatibility = Compatibility(extensions={"zip"}, media_types={"video"}, type_prefixes={"video-downloader"}, required_settings={("video-downloader.ffmpeg_path", is_executable)})

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
