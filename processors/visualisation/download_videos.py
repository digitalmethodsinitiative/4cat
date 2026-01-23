"""
Download videos from URLs

First attempt to download via request, but if that fails use yt-dlp.
"""
import json
import re
import shutil
import time
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import requests
import yt_dlp
from ural import urls_from_text
from yt_dlp import DownloadError
from yt_dlp.utils import ExistingVideoReached

from backend.lib.processor import BasicProcessor
from backend.lib.proxied_requests import FailedProxiedRequest
from common.lib.dataset import DataSet
from common.lib.exceptions import ProcessorInterruptedException, ProcessorException, DataSetException
from common.lib.helpers import UserInput, sets_to_lists, url_to_filename

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


# Custom Exception Classes
class MaxVideosDownloaded(ProcessorException):
    """
    Raise if too many videos have been downloaded and the processor should stop future downloads
    """
    pass


class FailedDownload(ProcessorException):
    """
    Raise if Download failed and will not be tried again
    """
    pass


class VideoStreamUnavailable(ProcessorException):
    """
    Raise request stream does not contain video, BUT URL may be able to be processed by YT-DLP
    """
    pass


class NotAVideo(ProcessorException):
    """
    Raise if we know URL does not contain video OR URL that YT-DLP can handle
    """
    pass


class FilesizeException(ProcessorException):
    """
    Raise if video size does not meet criteria
    """
    pass


class LiveVideoException(ProcessorException):
    """
    Raise if live videos are not allowed
    """
    pass


class FailedToCopy(ProcessorException):
    """
    Raise if unable to copy video from previous dataset
    """
    pass


class VideoDownloaderPlus(BasicProcessor):
    """
    Downloads videos and saves as zip archive

    Attempts to download videos directly, but if that fails, uses YT_DLP. (https://github.com/yt-dlp/yt-dlp/#readme)
    which attempts to keep up with a plethora of sites: https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md
    """
    type = "video-downloader"  # job type ID
    category = "Visual"  # category
    title = "Download videos"  # title displayed in UI
    description = "Download videos from URLs and store in a zip file. May take a while to complete as videos are " \
                  "retrieved externally."  # description displayed in UI
    extension = "zip"  # extension of result file, used internally and in UI
    media_type = "video"  # media type of the processor

    followups = ["audio-extractor", "metadata-viewer", "video-scene-detector", "preset-scene-timelines", "video-stack", "preset-video-hashes", "video-hasher-1", "video-frames"]

    references = [
        "[YT-DLP python package](https://github.com/yt-dlp/yt-dlp/#readme)",
        "[Supported sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md)",
    ]

    known_channels = ['youtube.com/c/', 'youtube.com/channel/']

    # Some datasets have known mixed media types; do not stop due to many "Not a video" errors
    mixed_media_dataset_types = ["instagram-search"]
    DIRECT_DOWNLOAD_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:107.0) Gecko/20100101 Firefox/107.0"

    config = {
        "video-downloader.ffmpeg_path": {
            "type": UserInput.OPTION_TEXT,
            "default": "ffmpeg",
            "help": "Path to ffmpeg",
            "tooltip": "Where to find the ffmpeg executable. ffmpeg is required by many of the video-related "
                       "processors which will be unavailable if no executable is available in this path."
        },
        "video-downloader.max": {
            "type": UserInput.OPTION_TEXT,
            "coerce_type": int,
            "default": 1000,
            "help": "Max number of videos to download",
            "tooltip": "Only allow downloading up to this many videos per batch. Increasing this can lead to "
                       "long-running processors and large datasets. Set to 0 for no limit."
        },
        "video-downloader.max-size": {
            "type": UserInput.OPTION_TEXT,
            "coerce_type": int,
            "default": 100,
            "help": "Max allowed MB size per video",
            "tooltip": "Size in MB/Megabytes; default 100. 0 will allow any size."
        },
        "video-downloader.allow-unknown-size": {
            "type": UserInput.OPTION_TOGGLE,
            "default": True,
            "help": "Allow video download of unknown size",
            "tooltip": "Video size is not always available before downloading. If True, users may choose to download "
                       "videos with unknown sizes."
        },
        "video-downloader.allow-indirect": {
            "type": UserInput.OPTION_CHOICE,
            "default": "none",
            "options": {"none": "No indirect links", "yt_only": "YouTube only", "all": "All links"},
            "help": "Allow indirect downloads",
            "tooltip": "Allow users to choose to download videos linked indirectly (e.g. embedded in a linked tweet, link to a YouTube video). "
                       "Enabling all can be confusing for users and download more than intended."
        },
        "video-downloader.allow-multiple": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Allow multiple videos per item",
            "tooltip": "Allow users to choose to download videos from links that refer to multiple videos. For "
                       "example, for a given link to a YouTube channel all videos for that channel are downloaded."
        },
        # Allow overriding "Not a video" limit
        "video-downloader.ignore-errors": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Allow option to ignore \"Not a video\" limit",
            "tooltip": "If links are not videos, continue attempts. Useful for mixed datasets (e.g. Instagram \"media_urls\" where many are images)."
        },
    }

    def __init__(self, logger, job, queue=None, manager=None, modules=None):
        super().__init__(logger, job, queue, manager, modules)
        self.max_videos_per_url = 1
        self.videos_downloaded_from_url = None
        self.downloaded_videos = 0
        self.total_possible_videos = 5
        self.url_files = None
        self.last_dl_status = None
        self.last_post_process_status = None
        self.warning_message = None

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
        """
        Updating columns with actual columns and setting max_number_videos per
        the max number of images allowed.
        :param config:
        """
        options = {
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "help": "No. of videos (max 1000)",
                "default": 100,
                "min": 0,
            },
            "columns": {
                "type": UserInput.OPTION_TEXT,
                "help": "Column to get video links from",
                "inline": True,
                "tooltip": "If the column contains a single URL, use that URL; else, try to find image URLs in the "
                        "column's content"
            },
            "max_video_size": {
                "type": UserInput.OPTION_TEXT,
                "help": "Max videos size (in MB/Megabytes)",
                "default": 100,
                "min": 1,
                "tooltip": "Max of 100 MB set by 4CAT administrators",
            },
            "split-comma": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Split column values by comma",
                "default": True,
                "tooltip": "If enabled, columns can contain multiple URLs separated by commas, which will be considered "
                        "separately"
            }
        }

        # Update the amount max and help from config
        max_number_videos = int(config.get('video-downloader.max', 100))
        if max_number_videos == 0:
            options['amount']['help'] = "No. of videos"
            options["amount"]["tooltip"] = "Use 0 to download all videos"
        else:
            options['amount']['max'] = max_number_videos
            options['amount']['help'] = f"No. of videos (max {max_number_videos:,})"

        # And update the max size and help from config
        max_video_size = int(config.get('video-downloader.max-size', 100))
        if max_video_size == 0:
            # Allow video of any size
            options["max_video_size"]["tooltip"] = "Set to 0 if all sizes are to be downloaded."
            options['max_video_size']['min'] = 0
        else:
            # Limit video size
            options["max_video_size"]["max"] = max_video_size
            options['max_video_size']['default'] = options['max_video_size']['default'] if options['max_video_size'][
                                                                                       'default'] <= max_video_size else max_video_size
            options["max_video_size"]["tooltip"] = f"Cannot be more than {max_video_size}MB."
            options['max_video_size']['min'] = 1

        # Get the columns for the select columns option
        if parent_dataset and parent_dataset.get_columns():
            columns = parent_dataset.get_columns()
            options["columns"]["type"] = UserInput.OPTION_MULTI
            options["columns"]["options"] = {v: v for v in columns}

            # Figure out default column
            priority = ["video_url", "video_link", "video", "media_url", "media_link", "media", "final_url", "url", "link", "body"]
            columns.sort(key=lambda col: next((i for i, p in enumerate(priority) if p in col.lower()), len(priority)))
            options["columns"]["default"] = [columns.pop(0)]

        # Allow overriding error limit
        if parent_dataset and parent_dataset.type in cls.mixed_media_dataset_types: 
            # Override is automatic
            pass
        elif config.get("video-downloader.ignore-errors", False):
            # Allow user to choose to ignore "Not a video" errors
            options["ignore_not_video"] = {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Ignore \"Not a video\" limit",
                "default": False,
                "tooltip": "If blocked or links are not videos, continue attempts. Useful for mixed datasets (e.g. Instagram \"media_urls\" where many are images)."
            }

        # these two options are likely to be unwanted on instances with many
        # users, so they are behind an admin config options
        indirect_setting = config.get("video-downloader.allow-indirect", "none")
        if indirect_setting and indirect_setting != "none":
            possible_options = {"none": "No indirect links", "yt_only": "YouTube links"}
            if indirect_setting == "all":
                possible_options["all"] = "Attempt all links"
            options["also_indirect"] = {
                "type": UserInput.OPTION_CHOICE,
                "default": "none",
                "help": "Also attempt to download non-direct videos link?",
                "options": possible_options,
                "tooltip": "4CAT will always download directly linked videos (works with fields like Twitter's \"video\", TikTok's \"video_url\" or Instagram's \"media_url\"), but 4CAT can use YT-DLP to download from YouTube and a number of other video hosting sites (see references)."
            }
            
            options["max_video_res"] = {
                "type": UserInput.OPTION_TEXT,
                "help": "Max video resolution height (use 0 for any)",
                "coerce_type": int,
                "default": 0,
                "min": 0,
                "tooltip": "If 0, any resolution is allowed. Otherwise, only videos with a resolution less than or equal to this height will be downloaded (e.g. videos less than 480p).",
                "requires": "also_indirect!=none"
            }

        if config.get("video-downloader.allow-multiple"):
            options["channel_videos"] = {
                                            "type": UserInput.OPTION_TEXT,
                                            "help": "Download multiple videos per link?",
                                            "default": 0,
                                            "min": 0,
                                            "max": 5,
                                            "requires": "also_indirect!=none",
                                            "tooltip": "If more than 0, links leading to multiple videos will be downloaded (e.g. a YouTube user's channel)"
                                        }
        if config.get('video-downloader.allow-unknown-size', False):
            options["allow_unknown_size"] = {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Allow unknown video sizes",
                "default": False,
                "tooltip": "If True, videos with unknown sizes will be downloaded (size filters still applies if known). Recommend on using if you are not able to download videos otherwise."
            }

        return options

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Determine compatibility

        Compatible with any top-level dataset. Could run on any type of dataset
        in principle, but any links to videos are likely to come from the top
        dataset anyway.

        :param module:  Module to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        :return bool:
        """
        return ((module.type.endswith("-search") or module.is_from_collector())
                # These have their own video downloaders
                and module.type not in ["tiktok-search", "tiktok-urls-search", "telegram-search"]) \
                and module.get_extension() in ("csv", "ndjson")

    def process(self):
        """
        This takes a 4CAT results file as input, and downloads video files
        referenced therein according to the processor parameters.
        """
        # Check processor able to run
        if self.source_dataset.num_rows == 0:
            self.dataset.finish_with_error("No data from which to extract video URLs.")
            return

        # Collect URLs
        try:
            urls = self.collect_video_urls()
        except ProcessorException as e:
            self.dataset.finish_with_error(str(e))
            return

        self.dataset.update_status('Collected %i urls.' % len(urls))

        vid_lib = DatasetVideoLibrary(self.dataset, modules=self.modules)

        # Prepare staging area for videos and video tracking
        results_path = self.dataset.get_staging_area()

        # Collect parameters
        also_indirect = self.parameters.get("also_indirect", "none")
        amount = self.parameters.get("amount", 100)
        if amount == 0:  # unlimited
            amount = self.config.get('video-downloader.max', 100)
        
        max_video_size = self.parameters.get("max_video_size", 100)
        max_video_res = self.parameters.get("max_video_res", 0)
        allow_unknown_sizes = self.parameters.get('allow_unknown_size', False)
        ignore_not_video = self.source_dataset.type in self.mixed_media_dataset_types or self.parameters.get("ignore_not_video", False)
        
        # Set up YT-DLP options (for fallback downloads)
        ydl_opts = self._setup_ytdlp_options(results_path, max_video_size, max_video_res, allow_unknown_sizes)

        # Set up download channels
        self.max_videos_per_url = self.parameters.get("channel_videos", 0)
        download_channels = self.max_videos_per_url > 0
        if self.max_videos_per_url == 0:
            self.max_videos_per_url = 1  # Ensure unknown channels only end up with one video downloaded

        # Initialize counters
        self.downloaded_videos = 0
        failed_downloads = 0
        copied_videos = 0
        consecutive_errors = 0
        # not_a_video tracked within direct_results
        total_not_a_video = 0
        skipped_urls = 0
        processed_urls = 0
        last_domains = []
        total_urls = len(urls)
        self.total_possible_videos = min(len(urls), amount) if amount != 0 else len(urls)
        yt_dlp_archive_map = {}

        # Process URLs in three tiers:
        # Tier 1: Check library and copy if available
        # Tier 2: Queue direct downloads
        # Tier 3: Fallback to yt-dlp if needed
        
        direct_download_queue = []
        ytdlp_fallback_queue = []

        # Tier 1: Library check and queue preparation
        self.dataset.update_status("Copying existing videos")
        for url in list(urls.keys()):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while collecting videos.")

            # Try to copy from library
            copy_result = self._try_copy_from_library(url, urls, vid_lib, results_path)
            if copy_result["copied"]:
                copied_videos += copy_result["count"]
                processed_urls += 1
                continue
            elif copy_result["skip"]:
                skipped_urls += 1
                total_not_a_video += 1
                continue

            # Initialize URL metadata
            urls[url]["success"] = False
            urls[url]["retry"] = True

            # Skip known channels if not downloading channels
            if not download_channels and any([sub_url in url for sub_url in self.known_channels]):
                message = 'Skipping known channel: %s' % url
                urls[url]['error'] = message
                failed_downloads += 1
                skipped_urls += 1
                self.dataset.log(message)
                continue

            # Queue for direct download attempt
            direct_download_queue.append(url)

        # Tier 2: Process direct downloads with proxies
        stop_processing = False
        stop_reason = None
        
        try:
            if direct_download_queue:
                self.dataset.update_status("Downloading videos directly")
                direct_results = self._process_direct_downloads(
                    direct_download_queue, urls, results_path, max_video_size,
                    also_indirect, amount, last_domains, ignore_not_video
                )
                
                processed_urls += direct_results["processed"]
                failed_downloads += direct_results["failed"]
                # Track not_a_video for logging purposes
                _ = direct_results["not_a_video_consecutive"]  # noqa: F841
                total_not_a_video += direct_results["not_a_video_total"]
                consecutive_errors = direct_results["consecutive_errors"]
                ytdlp_fallback_queue = direct_results["ytdlp_queue"]
                stop_processing = direct_results["stop_processing"]
                stop_reason = direct_results["stop_reason"]
                # Note: self.downloaded_videos already updated in real-time during processing

            # Handle stop conditions
            if stop_processing and stop_reason == "limit":
                for url in ytdlp_fallback_queue:
                    urls[url]["error"] = "Max video download limit already reached."
                ytdlp_fallback_queue = []
            elif stop_processing and stop_reason in {"errors", "no-videos"}:
                ytdlp_fallback_queue = []

            # Tier 3: YT-DLP fallback for indirect/complex URLs
            if ytdlp_fallback_queue and not stop_processing:
                self.dataset.update_status("Downloading videos with YT-DLP")
                ytdlp_results = self._process_ytdlp_downloads(
                    ytdlp_fallback_queue, urls, ydl_opts, results_path,
                    amount, also_indirect, yt_dlp_archive_map, consecutive_errors
                )
                
                failed_downloads += ytdlp_results["failed"]
                processed_urls += ytdlp_results["processed"]
        except ProcessorInterruptedException as e:
            # Interrupted; ensure we save metadata and finish with warning
            self.warning_message = str(e)
        except Exception as e:
            # This ensures dataset is finished_with_warning below in finally block
            self.warning_message = str(e)
            # Re-raise for logging and notification
            raise e
        finally:
            # Save metadata and finish
            self._save_metadata(urls, results_path)
            self._log_statistics(total_urls, processed_urls, skipped_urls, copied_videos, failed_downloads, total_not_a_video)
            self._finish_processing(results_path, copied_videos, failed_downloads, total_not_a_video, processed_urls, total_urls)

    def _setup_ytdlp_options(self, results_path, max_video_size, max_video_res, allow_unknown_sizes):
        """
        Set up YT-DLP options for fallback downloads
        
        :param Path results_path: Path to staging area
        :param int max_video_size: Maximum video size in MB
        :param int max_video_res: Maximum video resolution height
        :param bool allow_unknown_sizes: Whether to allow unknown file sizes
        :return dict: YT-DLP options dictionary
        """
        # YT-DLP advanced filter
        def dmi_match_filter(vid_info, *, incomplete):
            """
            Another method for ignoring specific videos.
            https://github.com/yt-dlp/yt-dlp#filter-videos
            """
            if vid_info.get('is_live'):
                raise LiveVideoException("4CAT settings do not allow downloading live videos with this processor")

        ydl_opts = {
            # "logger": self.log,  # This will dump any errors to our logger if desired
            "socket_timeout": 20,
            "download_archive": str(results_path.joinpath("video_archive")),
            "break_on_existing": True,
            "postprocessor_hooks": [self.yt_dlp_post_monitor],
            "progress_hooks": [self.yt_dlp_monitor],
            'match_filter': dmi_match_filter,
        }

        # Configure format filters based on size and resolution limits
        if max_video_size > 0 or max_video_res > 0:
            max_size = str(max_video_size) + "M"
            filesize_filter = f"[filesize<={max_size}]" if max_video_size > 0 else ""
            filesize_approx_filter = f"[filesize_approx<={max_size}]" if max_video_size > 0 else ""
            res_filter = f"[height<={max_video_res}]" if max_video_res > 0 else ""

            # Formats may be combined audio/video or separate streams
            if filesize_filter:
                ydl_opts["format"] = f"{res_filter}{filesize_filter}/bestvideo{res_filter}{filesize_filter}+bestaudio{filesize_filter}/{res_filter}{filesize_approx_filter}/bestvideo{res_filter}{filesize_approx_filter}+bestaudio{filesize_approx_filter}"
            else:
                ydl_opts["format"] = f"{res_filter}/bestvideo{res_filter}+bestaudio"

            if allow_unknown_sizes:
                ydl_opts["format"] += "/best/bestvideo+bestaudio"

            self.dataset.log(f"YT-DLP format filter: {ydl_opts['format']}")

        return ydl_opts

    def _try_copy_from_library(self, url, urls_dict, vid_lib, results_path):
        """
        Try to copy video from previously downloaded library
        
        :param str url: URL to check
        :param dict urls_dict: URLs dictionary to update
        :param DatasetVideoLibrary vid_lib: Video library instance
        :param Path results_path: Path to staging area
        :return dict: Result with 'copied', 'count', and 'skip' keys
        """
        result = {"copied": False, "count": 0, "skip": False}
        
        if url not in vid_lib.library:
            return result
            
        previous_vid_metadata = vid_lib.library[url]
        
        if previous_vid_metadata.get('success', False):
            # Use previous downloaded video
            try:
                self.dataset.log(f"Copying previously downloaded video for url: {url}")
                num_copied = self.copy_previous_video(previous_vid_metadata, results_path, vid_lib.previous_downloaders)
                urls_dict[url] = previous_vid_metadata
                self.dataset.update_status("Copied previously downloaded video to current dataset.")
                result["copied"] = True
                result["count"] = num_copied
            except FailedToCopy as e:
                self.dataset.log(f"{str(e)}; attempting to download again")
        elif previous_vid_metadata.get("retry", True) is False:
            urls_dict[url] = previous_vid_metadata
            self.dataset.log(f"Skipping; previously identified url as not a video: {url}")
            result["skip"] = True
            
        return result

    def _process_direct_downloads(self, url_list, urls_dict, results_path, max_video_size,
                                   also_indirect, amount, last_domains, ignore_not_video):
        """
        Process direct downloads using proxied requests
        
        :param list url_list: List of URLs to download directly
        :param dict urls_dict: URLs dictionary to update
        :param Path results_path: Path to staging area
        :param int max_video_size: Maximum video size in MB
        :param str also_indirect: Whether to use yt-dlp for indirect links
        :param int amount: Maximum number of videos to download
        :param list last_domains: List of last domains processed
        :param bool ignore_not_video: Whether to ignore "not a video" errors
        :return dict: Results dictionary with counters and queues
        """
        results = {
            "processed": 0,
            "failed": 0,
            "not_a_video_consecutive": 0,
            "not_a_video_total": 0,
            "consecutive_errors": 0,
            "ytdlp_queue": [],
            "stop_processing": False,
            "stop_reason": None
        }
        
        direct_requests = [{"original_url": url, "request_url": self._normalize_direct_url(url)} for url in url_list]
        request_urls = [entry["request_url"] for entry in direct_requests]
        task_iter = iter(direct_requests)
        processed_count = 0
        
        try:
            for _, response in self.iterate_proxied_requests(
                request_urls,
                preserve_order=True,
                headers={"User-Agent": self.DIRECT_DOWNLOAD_UA},
                stream=True,
                timeout=20,
            ):
                task = next(task_iter)
                processed_count += 1
                url = task["original_url"]
                
                if self.interrupted:
                    self.flush_proxied_requests()
                    raise ProcessorInterruptedException("Interrupted while downloading videos.")

                domain = urlparse(url).netloc
                last_domains = last_domains[-4:] + [domain]

                # Process the response
                download_result = self._handle_direct_download_response(
                    url, response, urls_dict, results_path, max_video_size,
                    also_indirect, domain, last_domains, ignore_not_video
                )
                
                # Update counters based on result
                if download_result["success"]:
                    results["processed"] += 1
                    results["not_a_video_consecutive"] = 0
                    results["consecutive_errors"] = 0
                    # Update downloaded count immediately for accurate limit checking
                    num_files = len(urls_dict[url].get("files", []))
                    self.downloaded_videos += num_files
                    self._update_download_status()
                elif download_result["fallback_to_ytdlp"]:
                    results["ytdlp_queue"].append(url)
                elif download_result["not_a_video"]:
                    results["processed"] += 1
                    results["not_a_video_consecutive"] += 1
                    results["not_a_video_total"] += 1
                elif download_result["error"]:
                    results["processed"] += 1
                    results["failed"] += 1
                    if download_result.get("timeout"):
                        results["consecutive_errors"] += 1
                
                # Check stop conditions
                if download_result.get("stop_action"):
                    self.flush_proxied_requests()
                    results["stop_processing"] = True
                    results["stop_reason"] = download_result.get("stop_reason", "errors")
                    break
                    
                # Check download limit (counter already updated above)
                if download_result["success"] and amount != 0:
                    if self.downloaded_videos >= amount:
                        results["stop_processing"] = True
                        results["stop_reason"] = "limit"
                        break

        except ProcessorInterruptedException:
            self.flush_proxied_requests()
            raise
        finally:
            if results["stop_processing"]:
                self.flush_proxied_requests()
                # Mark remaining URLs with appropriate error
                for pending in direct_requests[processed_count:]:
                    pending_url = pending["original_url"]
                    if results["stop_reason"] == "limit":
                        urls_dict[pending_url]["error"] = "Max video download limit already reached."

        return results

    def _handle_direct_download_response(self, url, response, urls_dict, results_path, max_video_size,
                                          also_indirect, domain, last_domains, ignore_not_video):
        """
        Handle a single direct download response
        
        :param str url: URL being processed
        :param response: Response object from proxied request
        :param dict urls_dict: URLs dictionary to update
        :param Path results_path: Path to staging area
        :param int max_video_size: Maximum video size in MB
        :param str also_indirect: Whether to use yt-dlp for indirect links
        :param str domain: Domain of the URL
        :param list last_domains: List of last domains processed
        :param bool ignore_not_video: Whether to ignore "not a video" errors
        :return dict: Result dictionary with success, error, fallback flags
        """
        result = {
            "success": False,
            "error": False,
            "not_a_video": False,
            "fallback_to_ytdlp": False,
            "timeout": False,
            "stop_action": None,
            "stop_reason": None
        }
        
        self.videos_downloaded_from_url = set()

        try:
            if isinstance(response, FailedProxiedRequest):
                error_context = response.context
                self.dataset.log(f"Request Error: {error_context}")
                urls_dict[url]["error"] = str(error_context)
                result["error"] = True
                
                if isinstance(error_context, requests.exceptions.Timeout):
                    result["timeout"] = True
                    action = self._handle_consecutive_error_stop(
                        result.get("consecutive_errors", 0) + 1, also_indirect
                    )
                    if action:
                        result["stop_action"] = action
                        result["stop_reason"] = "errors"
                return result

            filename, proxy_used = self._write_direct_response(url, response, results_path, max_video_size)
            urls_dict[url]["downloader"] = "direct_link"
            urls_dict[url]["files"] = [{
                "filename": filename,
                "metadata": {"proxy": proxy_used} if proxy_used else {},
                "success": True
            }]
            urls_dict[url]["success"] = True
            result["success"] = True
            self.videos_downloaded_from_url.add(filename)
            
        except VideoStreamUnavailable as e:
            if self._should_use_yt_dlp(url, also_indirect):
                result["fallback_to_ytdlp"] = True
            else:
                self.dataset.log(f"NotVideoLinkError: {str(e)}")
                urls_dict[url]["error"] = str(e)
                urls_dict[url]["retry"] = False
                result["not_a_video"] = True
                
                if last_domains.count(domain) >= 2:
                    time.sleep(5)
                    
                action = self._handle_non_video_stop(1, domain, last_domains, ignore_not_video)
                if action:
                    result["stop_action"] = action
                    result["stop_reason"] = "no-videos"
                    
        except NotAVideo as e:
            self.dataset.log(f"Request Error: {str(e)}")
            urls_dict[url]["error"] = str(e)
            urls_dict[url]["retry"] = False
            result["not_a_video"] = True
            
            if last_domains.count(domain) >= 2:
                time.sleep(5)
                
            action = self._handle_non_video_stop(1, domain, last_domains, ignore_not_video)
            if action:
                result["stop_action"] = action
                result["stop_reason"] = "no-videos"
                
        except (FilesizeException, FailedDownload) as e:
            self.dataset.log(f"Request Error: {str(e)}")
            urls_dict[url]["error"] = str(e)
            result["error"] = True
            
        except requests.exceptions.Timeout as e:
            self.dataset.log(f"Request Error: {str(e)}")
            urls_dict[url]["error"] = str(e)
            result["error"] = True
            result["timeout"] = True
            
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError, 
                requests.exceptions.TooManyRedirects) as e:
            self.dataset.log(f"Request Error: {str(e)}")
            urls_dict[url]["error"] = str(e)
            if not isinstance(e, requests.exceptions.TooManyRedirects):
                result["error"] = True
                
        finally:
            if hasattr(response, "close") and callable(response.close):
                try:
                    response.close()
                except Exception:
                    pass

        return result

    def _process_ytdlp_downloads(self, url_list, urls_dict, ydl_opts, results_path, 
                                  amount, also_indirect, yt_dlp_archive_map, consecutive_errors):
        """
        Process downloads using YT-DLP fallback
        
        :param list url_list: List of URLs to download with YT-DLP
        :param dict urls_dict: URLs dictionary to update
        :param dict ydl_opts: YT-DLP options
        :param Path results_path: Path to staging area
        :param int amount: Maximum number of videos to download
        :param str also_indirect: Whether indirect downloads are allowed
        :param dict yt_dlp_archive_map: Map of archive keys to file metadata
        :param int consecutive_errors: Current consecutive error count
        :return dict: Results dictionary with counters
        """
        results = {
            "processed": 0,
            "failed": 0,
        }
        
        for url in url_list:
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while downloading videos.")
                
            # Check download limit
            if amount != 0 and self.downloaded_videos >= amount:
                urls_dict[url]["error"] = "Max video download limit already reached."
                continue

            self.videos_downloaded_from_url = set()
            ydl_opts["outtmpl"] = str(results_path) + '/' + re.sub(r"[^0-9a-z]+", "_", url.lower())[:100] + '_%(autonumber)s.%(ext)s'
            
            ytdlp_result = self._download_single_ytdlp(url, ydl_opts, urls_dict, yt_dlp_archive_map)
            
            results["processed"] += 1
            
            if ytdlp_result["success"]:
                urls_dict[url]["success"] = True
                num_files = len(urls_dict[url].get("files", []))
                self.downloaded_videos += num_files
                self._update_download_status()
            else:
                results["failed"] += 1
                if ytdlp_result.get("should_stop"):
                    break
                    
        return results

    def _download_single_ytdlp(self, url, ydl_opts, urls_dict, yt_dlp_archive_map):
        """
        Download a single URL using YT-DLP
        
        :param str url: URL to download
        :param dict ydl_opts: YT-DLP options
        :param dict urls_dict: URLs dictionary to update
        :param dict yt_dlp_archive_map: Map of archive keys to file metadata
        :return dict: Result dictionary with success flag
        """
        result = {"success": False, "should_stop": False}
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            self.url_files = {}
            self.last_dl_status = {}
            self.last_post_process_status = {}
            self.dataset.update_status(f"Downloading {self.downloaded_videos + 1}/{self.total_possible_videos} via yt-dlp: {url}")
            
            try:
                ydl.extract_info(url)
                
            except MaxVideosDownloaded:
                self.dataset.log("Max videos for URL reached.")
                
            except ExistingVideoReached:
                self.dataset.log(f"Already downloaded video associated with: {url}")
                # Try to retrieve info about the existing video
                try:
                    with yt_dlp.YoutubeDL({"socket_timeout": 30}) as ydl2:
                        info2 = ydl2.extract_info(url, download=False)
                        if info2:
                            archive_key = info2.get('extractor') + info2.get('id')
                            if archive_key in yt_dlp_archive_map:
                                self.url_files[info2.get('_filename', {})] = yt_dlp_archive_map[archive_key]
                            else:
                                message = f"Video identified, but unable to identify which video from {url}"
                                self.dataset.log(message)
                                self.log.warning(message)
                except Exception as e:
                    self.dataset.log(f"Error retrieving existing video info: {str(e)}")
                    
            except (DownloadError, LiveVideoException) as e:
                error_str = str(e)
                if "Requested format is not available" in error_str:
                    message = "No format available for video (check max size/resolution settings and try again)"
                elif "Unable to download webpage: The read operation timed out" in error_str:
                    message = f'DownloadError: {error_str}'
                elif "Sign in to confirm you're not a bot." in error_str:
                    message = f'Sign in required: {error_str}'
                elif "HTTP Error 429: Too Many Requests" in error_str:
                    message = f'Too Many Requests: {error_str}'
                else:
                    message = f'DownloadError: {error_str}'
                    
                urls_dict[url]['error'] = message
                self.dataset.log(message)
                return result
                
            except Exception as e:
                self.dataset.log(f"YT-DLP raised unexpected error: {str(e)}")
                urls_dict[url]['error'] = f"YT-DLP raised unexpected error: {str(e)}"
                return result

        # Store results
        urls_dict[url]["downloader"] = "yt_dlp"
        urls_dict[url]['files'] = list(self.url_files.values())
        
        for file in self.url_files.values():
            archive_key = file.get('metadata', {}).get('extractor', '') + file.get('metadata', {}).get('id', '')
            if archive_key:
                yt_dlp_archive_map[archive_key] = file

        # Check if download was successful
        if self.last_dl_status.get('status') == 'finished' and self.last_post_process_status.get('status') == 'finished':
            result["success"] = True
            
        return result

    def _save_metadata(self, urls_dict, results_path):
        """Save metadata to JSON file"""
        self.dataset.update_status("Updating and saving metadata")
        metadata = {
            url: {
                "from_dataset": self.source_dataset.key,
                **sets_to_lists(data)
            } for url, data in urls_dict.items()
        }
        with results_path.joinpath(".metadata.json").open("w", encoding="utf-8") as outfile:
            json.dump(metadata, outfile)

    def _log_statistics(self, total_urls, processed_urls, skipped_urls, copied_videos, failed_downloads, total_not_a_video):
        """Log comprehensive download statistics"""
        self.dataset.log("=" * 60)
        self.dataset.log("VIDEO DOWNLOAD SUMMARY")
        self.dataset.log(f"Total URLs collected: {total_urls}")
        self.dataset.log(f"URLs processed (download attempted or copied): {processed_urls}")
        self.dataset.log(f"URLs skipped (previously failed, max limit, known channels): {skipped_urls}")
        self.dataset.log(f"URLs not reviewed: {total_urls - processed_urls - skipped_urls}")
        self.dataset.log(f"Videos successfully downloaded (new): {self.downloaded_videos}")
        self.dataset.log(f"Videos copied from previous downloads: {copied_videos}")
        self.dataset.log(f"Total videos in dataset: {self.downloaded_videos + copied_videos}")
        self.dataset.log(f"Download failures: {failed_downloads}")
        self.dataset.log(f"Not a video (URLs that don't lead to videos): {total_not_a_video}")
        self.dataset.log(f"URL review rate: {processed_urls}/{total_urls} ({100*processed_urls/total_urls if total_urls > 0 else 0:.1f}%)")
        self.dataset.log(f"Success rate (of processed URLs): {(self.downloaded_videos + copied_videos)}/{processed_urls} ({100*(self.downloaded_videos + copied_videos)/processed_urls if processed_urls > 0 else 0:.1f}%)")
        self.dataset.log("=" * 60)

    def _finish_processing(self, results_path, copied_videos, failed_downloads, total_not_a_video, processed_urls, total_urls):
        """Finish processing and create result archive"""
        self.dataset.update_status("Writing downloaded videos to zip archive")
        self.write_archive_and_finish(results_path, self.downloaded_videos + copied_videos, finish=False)
        
        status_msg = f"Downloaded {self.downloaded_videos} videos"
        if copied_videos > 0:
            status_msg += f"; {copied_videos} videos copied from previous downloads"
        if failed_downloads > 0:
            status_msg += f"; {failed_downloads} downloads failed."
        if total_not_a_video > 0:
            status_msg += f"; {total_not_a_video} URLs were not videos."
        if processed_urls > 0:
            status_msg += f"; Processed {processed_urls} URLs of {total_urls}."
        
        if self.warning_message:
            self.dataset.update_status(status_msg)
            self.dataset.finish_with_warning(self.downloaded_videos, f"Incomplete: {self.warning_message}")
        else:
            self.dataset.update_status(status_msg, is_final=True)
            self.dataset.finish(self.downloaded_videos)

    def yt_dlp_monitor(self, d):
        """Can be used to gather information from yt-dlp while downloading"""
        self.last_dl_status = d
        if len(self.videos_downloaded_from_url) != 0 and len(self.videos_downloaded_from_url) >= self.max_videos_per_url:
            raise MaxVideosDownloaded('Max videos for URL reached.')
        if self.interrupted:
            raise ProcessorInterruptedException("Interrupted while downloading videos.")

    def yt_dlp_post_monitor(self, d):
        """Can be used to gather information from yt-dlp while post processing the downloads"""
        self.last_post_process_status = d
        if d['status'] == 'finished':
            self.videos_downloaded_from_url.add(d.get('info_dict',{}).get('_filename', {}))
            self.url_files[d.get('info_dict',{}).get('_filename', {})] = {
                "filename": Path(d.get('info_dict').get('_filename')).name,
                "metadata": d.get('info_dict'),
                "success": True
            }
        if self.interrupted:
            raise ProcessorInterruptedException("Interrupted while downloading videos.")

    def _normalize_direct_url(self, url):
        """Normalize URL for direct download"""
        cleaned = (url or "").strip()
        if cleaned.startswith("//"):
            cleaned = f"https:{cleaned}"
        parsed = urlparse(cleaned)
        if not parsed.scheme:
            cleaned = f"https://{cleaned.lstrip(' :/')}"
        return cleaned

    def _write_direct_response(self, original_url, response, results_path, max_video_size):
        """Write direct download response to file"""
        try:
            max_video_size = int(max_video_size)
        except (TypeError, ValueError):
            max_video_size = 0
            
        if response.status_code == 403:
            raise VideoStreamUnavailable(f"Website denied download request (Code 403): {original_url}")
        elif 400 <= response.status_code < 500:
            raise FailedDownload(f"Website denied download request (Code {response.status_code} / Reason {response.reason}): {original_url}")
        if response.status_code != 200:
            raise FailedDownload(f"Unable to obtain URL (Code {response.status_code} / Reason {response.reason}): {original_url}")

        content_type = response.headers.get("Content-Type")
        if not content_type:
            raise VideoStreamUnavailable(f"Unable to verify video; no Content-Type provided: {original_url}")
            
        lowered_type = content_type.lower()
        if "image" in lowered_type:
            raise NotAVideo(f"Not a Video ({content_type}): {original_url}")
        if "video" not in lowered_type:
            raise VideoStreamUnavailable(f"Does not appear to be a direct to video link: {original_url}; Content-Type: {content_type}")

        extension = content_type.split(";")[0].split("/")[-1]
        if extension not in ["mp4", "mp3"]:
            self.dataset.log(f"DEBUG: Odd extension type {extension}; Notify 4CAT maintainers if video. Content-Type for url {original_url}: {content_type}")

        unique_filename = url_to_filename(original_url, staging_area=results_path, default_ext="." + extension)
        save_location = results_path.joinpath(unique_filename)

        if max_video_size != 0:
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > (max_video_size * 1000000):
                        raise FilesizeException(f"Video size {content_length} larger than maximum allowed per 4CAT")
                except ValueError:
                    pass
            elif not self.config.get("video-downloader.allow-unknown-size", False):
                raise FilesizeException("Video size unknown; not allowed to download per 4CAT settings")

        self.dataset.update_status(f"Downloading {self.downloaded_videos + 1}/{self.total_possible_videos} via requests: {original_url}")
        
        bytes_written = 0
        max_bytes = max_video_size * 1000000 if max_video_size else 0
        
        with save_location.open("wb") as outfile:
            try:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    outfile.write(chunk)
                    bytes_written += len(chunk)
                    if max_bytes and bytes_written > max_bytes:
                        raise FilesizeException("Video size larger than maximum allowed per 4CAT")
            except FilesizeException:
                outfile.close()
                save_location.unlink(missing_ok=True)
                raise
            except requests.exceptions.ChunkedEncodingError as e:
                outfile.close()
                save_location.unlink(missing_ok=True)
                raise FailedDownload(f"Failed to complete download: {e}")
            except Exception:
                outfile.close()
                save_location.unlink(missing_ok=True)
                raise
                
        return save_location.name, getattr(response, "_4cat_proxy", None)

    def _should_use_yt_dlp(self, url, also_indirect):
        """Determine if YT-DLP should be used for this URL"""
        if also_indirect == "all":
            return True
        if also_indirect == "yt_only":
            netloc = urlparse(url).netloc.lower()
            return netloc == 'youtu.be' or netloc == 'youtube.com' or netloc.endswith('.youtube.com')
        return False

    def _handle_non_video_stop(self, not_a_video, domain, last_domains, ignore_not_video=False):
        """Handle stopping condition for too many non-video URLs"""
        if ignore_not_video:
            return None
        if not_a_video < 10:
            return None
        if last_domains.count(domain) < 5:
            return None
            
        allow_indirect = self.config.get('video-downloader.allow-indirect')
        message = "Too many consecutive non-video URLs encountered; " + (
            "try again with Non-direct videos option selected" if allow_indirect else "try extracting URLs and filtering dataset first"
        )
        self.warning_message = message
        self.dataset.update_status(message)
        return message 

    def _handle_consecutive_error_stop(self, consecutive_errors, also_indirect):
        """Handle stopping condition for too many consecutive errors"""
        if consecutive_errors < 5:
            return None
            
        if also_indirect != "none":
            message = f"Downloaded {self.downloaded_videos} videos. Errors {consecutive_errors} consecutive times; try deselecting the non-direct videos setting"
        else:
            message = f"Downloaded {self.downloaded_videos} videos. Errors {consecutive_errors} consecutive times; check logs to ensure video URLs are working links and you are not being blocked."
        self.warning_message = message
        self.dataset.update_status(message)
        return message 

    def _update_download_status(self):
        """Update download progress status"""
        status = f"Downloaded {self.downloaded_videos}/{self.total_possible_videos} videos"
        self.dataset.update_status(status)
        
        if self.total_possible_videos:
            progress = min(1, self.downloaded_videos / self.total_possible_videos)
            self.dataset.update_progress(progress)

    def collect_video_urls(self, *args, **kwargs):
        """Collect video URLs from the source dataset"""
        urls = {}
        columns = self.parameters.get("columns")
        if type(columns) is str:
            columns = [columns]

        if not columns:
            raise ProcessorException("No columns selected; cannot collect video urls.")

        self.dataset.update_status("Reading source file")
        for index, post in enumerate(self.source_dataset.iterate_items(self)):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while collecting video URLs.")
            item_urls = set()
            if index + 1 % 250 == 0:
                self.dataset.update_status(f"Extracting video links from item {index + 1}/{self.source_dataset.num_rows}")

            for column in columns:
                value = post.get(column)
                if not value:
                    continue

                if value is not str:
                    value = str(value)

                video_links = self.identify_video_urls_in_string(value)
                if video_links:
                    item_urls |= set(video_links)

            for item_url in item_urls:
                if item_url not in urls:
                    urls[item_url] = {'post_ids': {post.get('id')}}
                else:
                    urls[item_url]['post_ids'].add(post.get('id'))

        if not urls:
            raise ProcessorException("No video urls identified in provided data.")
        return urls

    def identify_video_urls_in_string(self, text):
        """Search string of text for URLs that may contain video links"""
        split_comma = self.parameters.get("split-comma", True)
        if split_comma:
            texts = text.split(",")
        else:
            texts = [text]

        urls = set()
        for string in texts:
            urls |= set([url for url in urls_from_text(string)])
        return list(urls)

    def copy_previous_video(self, previous_vid_metadata, staging_area, previous_downloaders):
        """Copy existing video to new staging area"""
        num_copied = 0
        dataset_key = previous_vid_metadata.get("file_dataset_key")
        dataset = [dataset for dataset in previous_downloaders if dataset.key == dataset_key]

        if "files" in previous_vid_metadata:
            files = previous_vid_metadata.get('files')
        elif "filename" in previous_vid_metadata:
            files = [{"filename": previous_vid_metadata.get("filename"), "success": True}]
        else:
            raise FailedToCopy("Unable to read video metadata")

        if not files:
            raise FailedToCopy("No file found in metadata")

        if not dataset:
            raise FailedToCopy(f"Dataset with key {dataset_key} not found")
        else:
            dataset = dataset[0]

        with zipfile.ZipFile(dataset.get_results_path(), "r") as archive_file:
            archive_contents = sorted(archive_file.namelist())

            for file in files:
                if file.get("filename") not in archive_contents:
                    raise FailedToCopy(f"Previously downloaded video {file.get('filename')} not found")

                self.dataset.log(f"Copying previously downloaded video {file.get('filename')} to new staging area")
                archive_file.extract(file.get("filename"), staging_area)
                num_copied += 1

        return num_copied

    @staticmethod
    def map_metadata(url, data):
        """Iterator to yield modified metadata for CSV"""
        row = {
            "url": url,
            "number_of_posts_with_url": len(data.get("post_ids", [])),
            "post_ids": ", ".join(data.get("post_ids", [])),
            "downloader": data.get("downloader", ""),
            "download_successful": data.get('success', "")
        }

        for file in data.get("files", [{}]):
            row["filename"] = file.get("filename", "N/A")
            yt_dlp_data = file.get("metadata", {})
            for common_column in ["title", "artist", "description", "view_count", "like_count", "repost_count", "comment_count", "uploader", "creator", "uploader_id"]:
                if yt_dlp_data:
                    row[f"extracted_{common_column}"] = yt_dlp_data.get(common_column)
                else:
                    row[f"extracted_{common_column}"] = "N/A"
            row["error"] = data.get("error", "N/A")
            yield row


class DatasetVideoLibrary:
    """
    Library for managing video downloads across multiple processors
    """
    def __init__(self, current_dataset, modules):
        self.modules = modules
        self.current_dataset = current_dataset
        self.previous_downloaders = self.collect_previous_downloaders()
        self.current_dataset.log(f"Previously video downloaders: {[downloader.key for downloader in self.previous_downloaders]}")

        metadata_files = self.collect_all_metadata_files()

        # Build library
        library = {}
        for metadata_file in metadata_files:
            for url, data in metadata_file[1].items():
                if data.get("success", False):
                    # Always overwrite for success
                    library[url] = {
                        **data,
                        "file_dataset_key": metadata_file[0]
                    }
                elif url not in library:
                    # Do not overwrite failures, but do add if missing
                    library[url] = {
                        **data,
                        "file_dataset_key": metadata_file[0]
                    }

        self.current_dataset.log(f"Total URLs previously seen: {len(library)}")
        self.library = library

    def collect_previous_downloaders(self):
        """
        Check for other video-downloader processors run on the dataset and create library for reference
        """
        # NOTE: this only checks parent dataset, not full ancestry (e.g. other filters with video downloaders)
        parent_dataset = self.current_dataset.get_parent()
        # Note: exclude current dataset
        previous_downloaders = [child for child in parent_dataset.get_children() if 
                              (child.type in ["video-downloader"] and child.key != self.current_dataset.key)]

        # Check to see if filtered dataset
        if "copied_from" in parent_dataset.parameters and parent_dataset.is_top_dataset():
            try:
                original_dataset = DataSet(key=parent_dataset.parameters["copied_from"], db=self.current_dataset.db, modules=self.modules)
                previous_downloaders += [child for child in original_dataset.top_parent().get_children() if
                                         (child.type in ["video-downloader"] and child.key != self.current_dataset.key)]
            except DataSetException:
                # parent dataset no longer exists!
                pass

        return previous_downloaders

    def collect_metadata_file(self, dataset, staging_area):
        """Collect metadata from a dataset's video archive"""
        source_file = dataset.get_results_path()
        if not source_file.exists():
            return None

        with zipfile.ZipFile(dataset.get_results_path(), "r") as archive_file:
            archive_contents = sorted(archive_file.namelist())
            if '.metadata.json' not in archive_contents:
                return None

            archive_file.extract(".metadata.json", staging_area)

            with open(staging_area.joinpath(".metadata.json")) as file:
                return json.load(file)

    def collect_all_metadata_files(self):
        """Collect all metadata files from previous downloaders"""
        metadata_staging_area = self.current_dataset.get_staging_area()

        metadata_files = [(downloader.key, self.collect_metadata_file(downloader, metadata_staging_area)) 
                         for downloader in self.previous_downloaders]
        metadata_files = [file for file in metadata_files if file[1] is not None]
        self.current_dataset.log(f"Metadata files collected: {len(metadata_files)}; with {[len(urls[1]) for urls in metadata_files]}")

        # Delete staging area
        shutil.rmtree(metadata_staging_area)

        return metadata_files