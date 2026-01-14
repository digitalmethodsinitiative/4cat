"""
Download videos

First attempt to download via request, but if that fails use yt-dlp
"""
import json
import re
import time
import zipfile
from pathlib import Path
import requests
import yt_dlp
from ural import urls_from_text
from urllib.parse import urlparse
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
        # Allow overriding error limit
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
                and module.type not in ["tiktok-search", "tiktok-urls-search", "telegram-search"]) \
                and module.get_extension() in ("csv", "ndjson")

    def process(self):
        """
        This takes a 4CAT results file as input, and downloads video files
        referenced therein according to the processor parameters.
        """
        # Check processor able to run
        if self.source_dataset.num_rows == 0:
            self.dataset.update_status("No data from which to extract video URLs.", is_final=True)
            self.dataset.finish(0)
            return

        # Collect URLs
        try:
            urls = self.collect_video_urls()
        except ProcessorException as e:
            self.dataset.update_status(str(e), is_final=True)
            self.dataset.finish(0)
            return

        self.dataset.log('Collected %i urls.' % len(urls))

        vid_lib = DatasetVideoLibrary(self.dataset, modules=self.modules)

        # Prepare staging area for videos and video tracking
        results_path = self.dataset.get_staging_area()

        # YT-DLP advanced filter
        def dmi_match_filter(vid_info, *, incomplete):
            """
            Another method for ignoring specific videos.
            https://github.com/yt-dlp/yt-dlp#filter-videos
            """
            # Check if video is known to be live (there also exists a `was_live` tag if that's desired)
            if vid_info.get('is_live'):
                raise LiveVideoException("4CAT settings do not allow downloading live videos with this processor")

        # Use YT-DLP
        also_indirect = self.parameters.get("also_indirect", "none")

        # Set up YT-DLP options
        ydl_opts = {
            # "logger": self.log,  # This will dump any errors to our logger if desired
            "socket_timeout": 20,
            # TODO: if yt-dlp archive is used, it raises an error, but does not contain the archive info; how to then
            #  connect the URL to the previously downloaded video?! A second request without download_archive and
            #  download=False can get the `info` but need to then use that info to tie to the filename!
            "download_archive": str(results_path.joinpath("video_archive")),
            "break_on_existing": True,
            "postprocessor_hooks": [self.yt_dlp_post_monitor],
            # This function ensures no more than self.max_videos_per_url downloaded and can be used to monitor progress
            "progress_hooks": [self.yt_dlp_monitor],
            'match_filter': dmi_match_filter,
        }

        # Collect parameters
        amount = self.parameters.get("amount", 100)
        if amount == 0:  # unlimited
            amount = self.config.get('video-downloader.max', 100)

        # Set a maximum amount of videos that can be downloaded per URL and set
        # if known channels should be downloaded at all
        self.max_videos_per_url = self.parameters.get("channel_videos", 0)
        if self.max_videos_per_url == 0:
            # TODO: how to ensure unknown channels/playlists are not downloaded? Is it possible with yt-dlp?
            self.max_videos_per_url = 1  # Ensure unknown channels only end up with one video downloaded
            download_channels = False
        else:
            download_channels = True

        # YT-DLP by default attempts to download the best quality videos
        allow_unknown_sizes = self.parameters.get('allow_unknown_size', False)
        max_video_size = self.parameters.get("max_video_size", 100)
        max_size = str(max_video_size) + "M"
        max_video_res = self.parameters.get("max_video_res", 0)
        if max_video_size > 0 or max_video_res > 0:
            filesize_filter = ""
            filesize_approx_filter = ""
            res_filter = ""
            if max_video_size > 0:
                filesize_filter = f"[filesize<={max_size}]"
                filesize_approx_filter = f"[filesize_approx<={max_size}]"
            if max_video_res > 0:
                res_filter = f"[height<={max_video_res}]"

            # Formats may be combined audio/video or separate streams
            if filesize_filter:
                # Use both filesize and filesize_approx to ensure we get the best video available
                ydl_opts["format"] = f"{res_filter}{filesize_filter}/bestvideo{res_filter}{filesize_filter}+bestaudio{filesize_filter}/{res_filter}{filesize_approx_filter}/bestvideo{res_filter}{filesize_approx_filter}+bestaudio{filesize_approx_filter}"
            else:
                ydl_opts["format"] = f"{res_filter}/bestvideo{res_filter}+bestaudio"

            if allow_unknown_sizes:
                # Allow unknown sizes if no video meeting the criteria is found
                ydl_opts["format"] += "/best/bestvideo+bestaudio"

            self.dataset.log(f"YT-DLP format filter: {ydl_opts['format']}")
        
        # Ignore not a video limit
        ignore_not_video = self.source_dataset.type in self.mixed_media_dataset_types or self.parameters.get("ignore_not_video", False)

        # Loop through video URLs and download
        self.downloaded_videos = 0
        failed_downloads = 0
        copied_videos = 0
        consecutive_errors = 0
        not_a_video = 0  # Consecutive counter for breaking early
        total_not_a_video = 0  # Total count of non-video URLs
        skipped_urls = 0  # URLs skipped (already failed before, known channels, etc.)
        processed_urls = 0  # URLs actually attempted (download or copy)
        last_domains = []
        total_urls = len(urls)
        self.total_possible_videos = min(len(urls), amount) if amount != 0 else len(urls)
        yt_dlp_archive_map = {}
        direct_requests = []
        fallback_queue = []

        for url in list(urls.keys()):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while downloading videos.")

            # Check previously downloaded library
            if url in vid_lib.library:
                previous_vid_metadata = vid_lib.library[url]
                if previous_vid_metadata.get('success', False):
                    # Use previous downloaded video
                    try:
                        self.dataset.log(f"Copying previously downloaded video for url: {url}")
                        num_copied = self.copy_previous_video(previous_vid_metadata, results_path, vid_lib.previous_downloaders)
                        urls[url] = previous_vid_metadata
                        self.dataset.update_status("Copied previously downloaded video to current dataset.")
                        copied_videos += num_copied
                        processed_urls += 1
                        continue
                    except FailedToCopy as e:
                        self.dataset.log(f"{str(e)}; attempting to download again")
                elif previous_vid_metadata.get("retry", True) is False:
                    urls[url] = previous_vid_metadata
                    self.dataset.log(f"Skipping; previously identified url as not a video: {url}")
                    skipped_urls += 1
                    total_not_a_video += 1
                    continue

            urls[url]["success"] = False
            urls[url]["retry"] = True

            # Skip known channels if not downloading channels (yt_dlp can download entire channels/playlists)
            if not download_channels and any([sub_url in url for sub_url in self.known_channels]):
                message = 'Skipping known channel: %s' % url
                urls[url]['error'] = message
                failed_downloads += 1
                skipped_urls += 1
                self.dataset.log(message)
                continue

            # First we'll try to see if we can directly download the URL
            direct_requests.append({
                "original_url": url,
                "request_url": self._normalize_direct_url(url)
            })

        stop_processing = False
        stop_reason = None
        processed_direct = 0
        direct_user_agent = self.DIRECT_DOWNLOAD_UA

        if direct_requests:
            request_urls = [entry["request_url"] for entry in direct_requests]
            task_iter = iter(direct_requests)
            try:
                for _, response in self.iterate_proxied_requests(
                        request_urls,
                        preserve_order=True,
                        headers={"User-Agent": direct_user_agent},
                        stream=True,
                        timeout=20,
                ):
                    task = next(task_iter)
                    processed_direct += 1
                    url = task["original_url"]
                    success = False
                    self.videos_downloaded_from_url = set()

                    if self.interrupted:
                        self.flush_proxied_requests()
                        raise ProcessorInterruptedException("Interrupted while downloading videos.")

                    domain = urlparse(url).netloc
                    last_domains = last_domains[-4:] + [domain]
                    proxy_used = response.proxy_url if isinstance(response, FailedProxiedRequest) else getattr(response, "_4cat_proxy", None)

                    try:
                        if isinstance(response, FailedProxiedRequest):
                            error_context = response.context
                            self.dataset.log(f"Request Error: {error_context}")
                            urls[url]["error"] = str(error_context)
                            if isinstance(error_context, requests.exceptions.Timeout):
                                consecutive_errors += 1
                                failed_downloads += 1
                                processed_urls += 1
                                action = self._handle_consecutive_error_stop(consecutive_errors, also_indirect)
                                if action == "finish":
                                    self.flush_proxied_requests()
                                    return
                                if action == "break":
                                    stop_processing = True
                                    stop_reason = "errors"
                                    break
                            else:
                                failed_downloads += 1
                                processed_urls += 1
                            continue

                        filename, proxy_used = self._write_direct_response(url, response, results_path, max_video_size)
                        urls[url]["downloader"] = "direct_link"
                        urls[url]["files"] = [{
                            "filename": filename,
                            "metadata": {"proxy": proxy_used} if proxy_used else {},
                            "success": True
                        }]
                        success = True
                        self.videos_downloaded_from_url.add(filename)
                        processed_urls += 1

                    except VideoStreamUnavailable as e:
                        if self._should_use_yt_dlp(url, also_indirect):
                            fallback_queue.append(url)
                        else:
                            self.dataset.log(f"NotVideoLinkError: {str(e)}")
                            not_a_video += 1
                            total_not_a_video += 1
                            urls[url]["error"] = str(e)
                            urls[url]["retry"] = False
                            processed_urls += 1
                            if last_domains.count(domain) >= 2:
                                time.sleep(5 * not_a_video)
                            action = self._handle_non_video_stop(not_a_video, domain, last_domains, ignore_not_video)
                            if action == "finish":
                                self.flush_proxied_requests()
                                return
                            if action == "break":
                                stop_processing = True
                                stop_reason = "no-videos"
                                break
                        continue

                    except NotAVideo as e:
                        self.dataset.log(f"Request Error: {str(e)}")
                        not_a_video += 1
                        total_not_a_video += 1
                        urls[url]["error"] = str(e)
                        urls[url]["retry"] = False
                        processed_urls += 1
                        if last_domains.count(domain) >= 2:
                            time.sleep(5 * not_a_video)
                        action = self._handle_non_video_stop(not_a_video, domain, last_domains, ignore_not_video)
                        if action == "finish":
                            self.flush_proxied_requests()
                            return
                        if action == "break":
                            stop_processing = True
                            stop_reason = "no-videos"
                            break
                        continue

                    except FilesizeException as e:
                        self.dataset.log(f"Request Error: {str(e)}")
                        urls[url]["error"] = str(e)
                        failed_downloads += 1
                        processed_urls += 1
                        continue

                    except FailedDownload as e:
                        self.dataset.log(f"Request Error: {str(e)}")
                        urls[url]["error"] = str(e)
                        failed_downloads += 1
                        processed_urls += 1
                        continue

                    except requests.exceptions.Timeout as e:
                        self.dataset.log(f"Request Error: {str(e)}")
                        urls[url]["error"] = str(e)
                        consecutive_errors += 1
                        failed_downloads += 1
                        processed_urls += 1
                        action = self._handle_consecutive_error_stop(consecutive_errors, also_indirect)
                        if action == "finish":
                            self.flush_proxied_requests()
                            return
                        if action == "break":
                            stop_processing = True
                            stop_reason = "errors"
                            break
                        continue

                    except (requests.exceptions.SSLError, requests.exceptions.ConnectionError, requests.exceptions.TooManyRedirects) as e:
                        self.dataset.log(f"Request Error: {str(e)}")
                        urls[url]["error"] = str(e)
                        if not isinstance(e, requests.exceptions.TooManyRedirects):
                            failed_downloads += 1
                        processed_urls += 1
                        continue

                    finally:
                        if hasattr(response, "close") and callable(response.close):
                            try:
                                response.close()
                            except Exception:
                                pass

                    urls[url]["success"] = success
                    if success:
                        consecutive_errors = 0
                        not_a_video = 0
                        self.downloaded_videos += len(self.videos_downloaded_from_url)
                        self._update_download_status(copied_videos, failed_downloads)
                        if amount != 0 and self.downloaded_videos >= amount:
                            stop_processing = True
                            stop_reason = "limit"
                            break

            except ProcessorInterruptedException:
                self.flush_proxied_requests()
                raise
            finally:
                if stop_processing:
                    self.flush_proxied_requests()

        if stop_processing and stop_reason == "limit":
            for pending in direct_requests[processed_direct:]:
                urls[pending["original_url"]]["error"] = "Max video download limit already reached."
            for url in fallback_queue:
                urls[url]["error"] = "Max video download limit already reached."
            fallback_queue = []

        if stop_processing and stop_reason in {"errors", "no-videos"}:
            fallback_queue = []

        for url in fallback_queue:
            if stop_processing:
                break

            self.videos_downloaded_from_url = set()
            ydl_opts["outtmpl"] = str(results_path) + '/' + re.sub(r"[^0-9a-z]+", "_", url.lower())[:100] + '_%(autonumber)s.%(ext)s'
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self.url_files = {}
                self.last_dl_status = {}
                self.last_post_process_status = {}
                self.dataset.update_status("Downloading %i/%i via yt-dlp: %s" % (self.downloaded_videos + 1, self.total_possible_videos, url))
                try:
                    ydl.extract_info(url)
                except MaxVideosDownloaded:
                    self.dataset.log("Max videos for URL reached.")
                except ExistingVideoReached:
                    self.dataset.log("Already downloaded video associated with: %s" % url)
                    with yt_dlp.YoutubeDL({"socket_timeout": 30}) as ydl2:
                        info2 = ydl2.extract_info(url, download=False)
                        if info2:
                            archive_key = info2.get('extractor') + info2.get('id')
                            if archive_key in yt_dlp_archive_map:
                                self.url_files[info2.get('_filename', {})] = yt_dlp_archive_map[archive_key]
                                self.dataset.log("Already downloaded video associated with: %s" % url)
                            else:
                                message = f"Video identified, but unable to identify which video from {url}"
                                self.dataset.log(message)
                                self.log.warning(message)
                                if len(self.videos_downloaded_from_url) == 0:
                                    urls[url]['error'] = message
                                    continue
                        else:
                            message = f"Video identified, but unable to identify which video from {url}"
                            self.dataset.log(message)
                            self.log.warning(message)
                            if len(self.videos_downloaded_from_url) == 0:
                                urls[url]['error'] = message
                                continue
                except (DownloadError, LiveVideoException) as e:
                    if "Requested format is not available" in str(e):
                        self.dataset.log(f"Format Error: {str(e)}")
                        message = "No format available for video (check max size/resolution settings and try again)"
                    elif "Unable to download webpage: The read operation timed out" in str(e):
                        message = 'DownloadError: %s' % str(e)
                    elif "Sign in to confirm you’re not a bot." in str(e):
                        message = 'Sign in required: %s' % str(e)
                    elif "HTTP Error 429: Too Many Requests" in str(e):
                        message = 'Too Many Requests: %s' % str(e)
                    else:
                        message = 'DownloadError: %s' % str(e)
                    time.sleep(10 * consecutive_errors)
                    consecutive_errors += 1
                    urls[url]['error'] = message
                    failed_downloads += 1
                    self.dataset.log(message)
                    action = self._handle_consecutive_error_stop(consecutive_errors, also_indirect)
                    if action == "finish":
                        return
                    if action == "break":
                        stop_processing = True
                        break
                    continue
                except Exception as e:
                    self.dataset.log(f"YT-DLP raised unexpected error: {str(e)}")
                    message = "YT-DLP raised unexpected error: %s" % str(e)
                    urls[url]['error'] = message
                    failed_downloads += 1
                    self.dataset.log(message)
                    continue

            urls[url]["downloader"] = "yt_dlp"
            urls[url]['files'] = list(self.url_files.values())
            for file in self.url_files.values():
                yt_dlp_archive_map[file.get('metadata').get('extractor') + file.get('metadata').get('id')] = file

            success = all([
                self.last_dl_status.get('status') == 'finished',
                self.last_post_process_status.get('status') == 'finished'
            ])
            urls[url]["success"] = success
            if success:
                consecutive_errors = 0
                not_a_video = 0
            
            processed_urls += 1
            self.downloaded_videos += len(self.videos_downloaded_from_url)
            self._update_download_status(copied_videos, failed_downloads)
            if amount != 0 and self.downloaded_videos >= amount:
                stop_processing = True
                break

        self.dataset.update_status("Updating and saving metadata")
        # Save some metadata to be able to connect the videos to their source
        metadata = {
            url: {
                "from_dataset": self.source_dataset.key,
                **sets_to_lists(data)
                # TODO: This some shenanigans until I can figure out what to do with the info returned
            } for url, data in urls.items()
        }
        with results_path.joinpath(".metadata.json").open("w", encoding="utf-8") as outfile:
            json.dump(metadata, outfile)

        # Log comprehensive statistics
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

        # Finish up
        self.dataset.update_status("Writing downloaded videos to zip archive")
        self.write_archive_and_finish(results_path, self.downloaded_videos+copied_videos)
        
        self.dataset.update_status(f"Downloaded {self.downloaded_videos} videos" + 
                                   (f"; {copied_videos} videos copied from previous downloads" if copied_videos > 0 else "") +
                                   (f"; {failed_downloads} downloads failed." if failed_downloads > 0 else "") + 
                                   (f"; {total_not_a_video} URLs were not videos." if total_not_a_video > 0 else "") +
                                   (f"; Processed {processed_urls} URLs of {total_urls}." if processed_urls > 0 else ""),
                                   is_final=True)

    def yt_dlp_monitor(self, d):
        """
        Can be used to gather information from yt-dlp while downloading
        """
        self.last_dl_status = d

        # Check if Max Video Downloads already reached
        if len(self.videos_downloaded_from_url) != 0 and len(self.videos_downloaded_from_url) >= self.max_videos_per_url:
            # DO NOT RAISE ON 0! (22-12-8 max_videos_per_url should no longer ever be 0)
            raise MaxVideosDownloaded('Max videos for URL reached.')

        # Make sure we can stop downloads
        if self.interrupted:
            raise ProcessorInterruptedException("Interrupted while downloading videos.")

    def yt_dlp_post_monitor(self, d):
        """
        Can be used to gather information from yt-dlp while post processing the downloads
        """
        self.last_post_process_status = d
        if d['status'] == 'finished':  # "downloading", "error", or "finished"
            self.videos_downloaded_from_url.add(d.get('info_dict',{}).get('_filename', {}))
            self.url_files[d.get('info_dict',{}).get('_filename', {})] = {
                "filename": Path(d.get('info_dict').get('_filename')).name,
                "metadata": d.get('info_dict'),
                "success": True
            }

        # Make sure we can stop downloads
        if self.interrupted:
            raise ProcessorInterruptedException("Interrupted while downloading videos.")

    def download_video_with_requests(self, url, results_path, max_video_size, retries=0):
        """
        Download a video with the Python requests library

        :param str url:             Valid URL direct to video source
        :param results_path:        Path to location for video download
        :param int max_video_size:  Maximum size in Bytes for video; 0 allows any size
        :param int retries:         Current number of retries to request video
        :return str:  File name     Returns file name of the video after download
        """
        if retries > 1:
            # Currently, only allow 1 retry with newly formatted URL via InvalidSchema/MissingSchema exception
            raise FailedDownload('Retries exceeded')
        # Open stream
        user_agent = self.DIRECT_DOWNLOAD_UA
        try:
            normalized_url = self._normalize_direct_url(url)
            with requests.get(normalized_url, stream=True, timeout=20, headers={"User-Agent": user_agent}) as response:
                filename, _ = self._write_direct_response(url, response, results_path, max_video_size)
                return filename
        except (requests.exceptions.InvalidSchema, requests.exceptions.MissingSchema):
            # Reformat URLs that are missing or have invalid schema
            return self.download_video_with_requests('https://' + url.lstrip(' :/'), results_path, max_video_size, retries=retries+1)

    def _normalize_direct_url(self, url):
        cleaned = (url or "").strip()
        if cleaned.startswith("//"):
            cleaned = f"https:{cleaned}"
        parsed = urlparse(cleaned)
        if not parsed.scheme:
            cleaned = f"https://{cleaned.lstrip(' :/')}"
        return cleaned

    def _write_direct_response(self, original_url, response, results_path, max_video_size):
        try:
            max_video_size = int(max_video_size)
        except (TypeError, ValueError):
            max_video_size = 0
        if response.status_code == 403:
            # Using VideoStreamUnavailable here as 403 often indicates blocking and ytdlp may be able to handle
            raise VideoStreamUnavailable(f"Website denied download request (Code 403): {original_url}")
        elif 400 <= response.status_code < 500:
            raise FailedDownload(
                f"Website denied download request (Code {response.status_code} / Reason {response.reason}): {original_url}")
        if response.status_code != 200:
            raise FailedDownload(
                f"Unable to obtain URL (Code {response.status_code} / Reason {response.reason}): {original_url}")

        content_type = response.headers.get("Content-Type")
        if not content_type:
            raise VideoStreamUnavailable(f"Unable to verify video; no Content-Type provided: {original_url}")
        lowered_type = content_type.lower()
        if "image" in lowered_type:
            raise NotAVideo("Not a Video (%s): %s" % (content_type, original_url))
        if "video" not in lowered_type:
            raise VideoStreamUnavailable(f"Does not appear to be a direct to video link: {original_url}; "
                                         f"Content-Type: {content_type}")

        extension = content_type.split(";")[0].split("/")[-1]
        if extension not in ["mp4", "mp3"]:
            self.dataset.log(f"DEBUG: Odd extension type {extension}; Notify 4CAT maintainers if video. "
                             f"Content-Type for url {original_url}: {content_type}")

        unique_filename = url_to_filename(original_url, staging_area=results_path, default_ext="." + extension)
        save_location = results_path.joinpath(unique_filename)

        if max_video_size != 0:
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > (max_video_size * 1000000):
                        raise FilesizeException(
                            f"Video size {content_length} larger than maximum allowed per 4CAT")
                except ValueError:
                    pass
            elif not self.config.get("video-downloader.allow-unknown-size", False):
                raise FilesizeException("Video size unknown; not allowed to download per 4CAT settings")

        self.dataset.update_status(
            "Downloading %i/%i via requests: %s" % (self.downloaded_videos + 1, self.total_possible_videos, original_url))
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
        if also_indirect == "all":
            return True
        if also_indirect == "yt_only":
            netloc = urlparse(url).netloc.lower()
            return netloc == 'youtu.be' or netloc == 'youtube.com' or netloc.endswith('.youtube.com')
        return False

    def _handle_non_video_stop(self, not_a_video, domain, last_domains, ignore_not_video=False):
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
        self.dataset.update_status(message, is_final=True)
        if self.downloaded_videos == 0:
            self.dataset.finish(0)
            return "finish"
        return "break"

    def _handle_consecutive_error_stop(self, consecutive_errors, also_indirect):
        if consecutive_errors < 5:
            return None
        if also_indirect != "none":
            message = "Downloaded %i videos. Errors %i consecutive times; try deselecting the non-direct videos setting" % (
                self.downloaded_videos, consecutive_errors)
        else:
            message = "Downloaded %i videos. Errors %i consecutive times; check logs to ensure video URLs are working links and you are not being blocked." % (
                self.downloaded_videos, consecutive_errors)
        self.dataset.update_status(message, is_final=True)
        if self.downloaded_videos == 0:
            self.dataset.finish(0)
            return "finish"
        return "break"

    def _update_download_status(self, copied_videos, failed_downloads):
        status = f"Downloaded {self.downloaded_videos}/{self.total_possible_videos} videos"
        if copied_videos > 0:
            status += f"; videos copied from {copied_videos} previous downloads"
        if failed_downloads > 0:
            status += f"; {failed_downloads} URLs failed."
        self.dataset.update_status(status)
        if self.total_possible_videos:
            progress = min(1, self.downloaded_videos / self.total_possible_videos)
            self.dataset.update_progress(progress)

    def collect_video_urls(self):
        """
        Extract video URLs from a dataset

        :return dict:  Dict with URLs as keys and a dict with a "post_ids" key
        as value
        """
        urls = {}
        columns = self.parameters.get("columns")
        if type(columns) is str:
            columns = [columns]

        if not columns:
            raise ProcessorException("No columns selected; cannot collect video urls.")

        self.dataset.update_status("Reading source file")
        for index, post in enumerate(self.source_dataset.iterate_items(self)):
            item_urls = set()
            if index + 1 % 250 == 0:
                self.dataset.update_status(
                    "Extracting video links from item %i/%i" % (index + 1, self.source_dataset.num_rows))

            # loop through all columns and process values for item
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
        else:
            return urls

    def identify_video_urls_in_string(self, text):
        """
        Search string of text for URLs that may contain video links.

        :param str text:  string that may contain URLs
        :return list:  	  list containing validated URLs to videos
        """
        split_comma = self.parameters.get("split-comma", True)
        if split_comma:
            texts = text.split(",")
        else:
            texts = [text]

        # Currently extracting all links
        urls = set()
        for string in texts:
            urls |= set([url for url in urls_from_text(string)])
        return list(urls)

    def copy_previous_video(self, previous_vid_metadata, staging_area, previous_downloaders):
        """
        Copy existing video to new staging area
        """
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
        """
        Iterator to yield modified metadata for CSV

        :param str url:  string that may contain URLs
        :param dict data:  dictionary with metadata collected previously
        :yield dict:  	  iterator containing reformated metadata
        """
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
        #TODO: recursive this so we can check downloads from other filters? NO, make a central point and use the ORIGINAL key

        parent_dataset = self.current_dataset.get_parent()
        # Note: exclude current dataset
        previous_downloaders = [child for child in parent_dataset.get_children() if (child.type == "video-downloader" and child.key != self.current_dataset.key)]

        # Check to see if filtered dataset
        if "copied_from" in parent_dataset.parameters and parent_dataset.is_top_dataset():
            try:
                original_dataset = DataSet(key=parent_dataset.parameters["copied_from"], db=self.current_dataset.db, modules=self.modules)
                previous_downloaders += [child for child in original_dataset.top_parent().get_children() if
                                         (child.type == "video-downloader" and child.key != self.current_dataset.key)]
            except DataSetException:
                # parent dataset no longer exists!
                pass

        return previous_downloaders

    def collect_metadata_file(self, dataset, staging_area):
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
        import shutil
        metadata_staging_area = self.current_dataset.get_staging_area()

        metadata_files = [(downloader.key, self.collect_metadata_file(downloader, metadata_staging_area)) for downloader in self.previous_downloaders]
        metadata_files = [file for file in metadata_files if file[1] is not None]
        self.current_dataset.log(f"Metadata files collected: {len(metadata_files)}; with {[len(urls[0]) for urls in metadata_files]}")

        # Delete staging area
        shutil.rmtree(metadata_staging_area)

        return metadata_files


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
