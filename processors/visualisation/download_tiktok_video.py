"""
Download TikTok videos
"""
from common.lib.compatibility import Compatibility
from common.lib.exceptions import ProcessorException, ProcessorInterruptedException
from common.lib.helpers import UserInput
from processors.visualisation.download_videos import VideoDownloaderPlus


class TikTokVideoDownloader(VideoDownloaderPlus):
    """
    Download TikTok videos

    TikTok's video links stop working soon after they are collected, and TikTok
    no longer sends new ones in a page 4CAT can read. yt-dlp can still find the
    video on each post's own page, so every post's link is downloaded with
    yt-dlp, without first trying it as a video file.
    """
    type = "video-downloader-tiktok"  # job type ID
    category = "Visual"  # category
    title = "Download TikTok videos"  # title displayed in UI
    description = "Downloads the videos of TikTok posts. yt-dlp finds each video on the post's own page. Image " \
                  "posts are skipped, as they have no video."
    extension = "zip"
    media_type = "video"

    # this downloader always uses yt-dlp, so the "non-direct videos" option is not offered
    user_chooses_yt_dlp = False

    # coarse map spec; is_compatible_with (below) is the runtime truth -- it also accepts
    # tiktok uploads, which depends on the dataset label and can't be declared statically
    compatibility = Compatibility(type_prefixes={"tiktok-"}, top_dataset_only=True, preferred_followups=VideoDownloaderPlus.followups)

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
        """
        Get processor options

        The same number and size limits as the general video downloader. For an
        uploaded TikTok dataset, the column with the post links can be chosen.

        :param DataSet parent_dataset:  Dataset to download videos for
        :param ConfigManager|None config:  Configuration reader (context-aware)
        """
        options = VideoDownloaderPlus.get_options(config=config)
        options = {key: options[key] for key in ("amount", "max_video_size")}

        if parent_dataset and parent_dataset.type == "upload-search":
            columns = parent_dataset.get_columns() or []
            options["url_column"] = {
                "type": UserInput.OPTION_CHOICE,
                "help": "Column with TikTok post links",
                "options": {column: column for column in columns},
                "default": "tiktok_url",
                "tooltip": "Links to the posts themselves (e.g. https://www.tiktok.com/@user/video/123), not to "
                           "video files"
            }

        return options

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Allow processor TikTok datasets

        :param module: Dataset or processor to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        """
        return ((module.type.startswith("tiktok") and module.type.endswith("search"))
                or (module.type == "upload-search" and "tiktok" in module.get_label().lower()))

    def process(self):
        """
        Download the videos with yt-dlp
        """
        # Set `also_indirect` to "all" so that all post links are downloaded with yt-dlp.
        self.parameters["also_indirect"] = "all"
        super().process()

    def collect_video_urls(self, *args, **kwargs):
        """
        Collect the links of the TikTok posts to download videos from

        All of them are downloaded with yt-dlp. Image posts are left out: they
        have no video, and yt-dlp would download only their sound.

        :return tuple:  Links to download directly (none), and the post links
        to download with yt-dlp
        """
        url_column = self.parameters.get("url_column") or "tiktok_url"
        post_links = {}
        image_posts = 0
        without_link = 0

        self.dataset.update_status("Reading source file")
        for post in self.source_dataset.iterate_items(self):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while collecting TikTok post links.")

            link = str(post.get(url_column) or "").strip()
            if post.get("is_image_post") == "yes" or "/photo/" in link:
                image_posts += 1
                continue

            if not link.startswith(("http://", "https://")):
                without_link += 1
                continue

            post_links.setdefault(link, {"post_ids": set()})["post_ids"].add(post.get("id"))

        if image_posts:
            self.dataset.log(f"Skipping {image_posts:,} image post(s), which have no video")
        if without_link:
            self.dataset.log(f"Skipping {without_link:,} post(s) without a link in column '{url_column}'")

        if not post_links:
            if image_posts and not without_link:
                raise ProcessorException("No videos to download: all posts in this dataset are image posts.")
            raise ProcessorException(f"No TikTok post links found in column '{url_column}'.")

        return {}, post_links

    def _download_single_ytdlp(self, url, ydl_opts, urls_dict):
        """
        Download a post's video with yt-dlp, trying once more if TikTok refuses the video file

        TikTok sometimes sends a post's page without the cookie (`ttwid`) its video servers
        ask for and these then refuse the video file (HTTP 403). Loading the page again usually
        gets the cookie, so the post is tried once more, as a new yt-dlp session.

        :param str url:  Link to the post
        :param dict ydl_opts:  yt-dlp options
        :param dict urls_dict:  Results per link, updated in place
        :return dict:  Whether the download succeeded, and whether a failure
        suggests TikTok is not letting us download
        """
        result = super()._download_single_ytdlp(url, ydl_opts, urls_dict)

        error = urls_dict[url].get("error") or ""
        if result["success"] or "unable to download video data: HTTP Error 403" not in error:
            return result

        self.dataset.log(f"TikTok refused the video file; trying once more with a new session: {url}")
        urls_dict[url].pop("error", None)
        return super()._download_single_ytdlp(url, ydl_opts, urls_dict)
