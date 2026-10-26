"""
Download Weibo videos
"""
from backend.lib.preset import ProcessorPreset
from common.lib.compatibility import Compatibility
from processors.visualisation.download_videos import VideoDownloaderPlus


class WeiboVideoDownloader(ProcessorPreset):
    """
    Download Weibo videos

    This is a Preset that runs the VideoDownloaderPlus with set parameters.
    Weibo's video links stop working about an hour after they were collected,
    so when a link no longer works, yt-dlp looks up the video on the post's
    own page instead.
    """
    type = "video-downloader-weibo"  # job type ID
    category = "Visual"  # category
    title = "Download Weibo videos"  # title displayed in UI
    description = "Downloads the videos in Weibo posts. Weibo's video links stop working about an hour after they " \
                  "are collected; for those, yt-dlp finds the video on the post's own page instead."
    extension = "zip"
    media_type = "video"

    compatibility = Compatibility(types={"weibo-search"}, top_dataset_only=True, preferred_followups=VideoDownloaderPlus.followups)

    references = [
        "[YT-DLP python package](https://github.com/yt-dlp/yt-dlp/#readme)",
    ]

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
        """
        Get processor options

        The same number and size limits as the general video downloader.

        :param DataSet parent_dataset:  Dataset to download videos for
        :param ConfigManager|None config:  Configuration reader (context-aware)
        """
        options = VideoDownloaderPlus.get_options(config=config)
        return {key: options[key] for key in ("amount", "max_video_size")}

    def get_processor_pipeline(self):
        """
        This queues the video-downloader with set options
        """
        return [
            {
                "type": "video-downloader",
                "parameters": {
                    "amount": self.parameters.get("amount"),
                    "max_video_size": self.parameters.get("max_video_size"),
                    "columns": ["video_url"],
                    "also_indirect": "all",  # enables yt-dlp
                    "_ytdlp_fallback_column": "url",  # yt-dlp uses the Weibo post URL
                    # posts without a video link have no video, so yt-dlp would not find one on their page either
                    "_ytdlp_fallback_without_video_link": False,
                }
            },
        ]
