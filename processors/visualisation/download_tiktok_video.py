"""
Download Tiktok videos
"""
import csv
import json

from bs4 import BeautifulSoup

from backend.lib.preset import ProcessorPreset
from backend.lib.proxied_requests import FailedProxiedRequest
from common.lib.helpers import UserInput
from processors.visualisation.download_videos import VideoDownloaderPlus
from backend.lib.processor import BasicProcessor
from datasources.tiktok_urls.search_tiktok_urls import TikTokScraper
from common.lib.compatibility import Compatibility

class TikTokVideoDownloader(ProcessorPreset):
    """
    Download TikTok videos

    This is a Preset that runs the VideoDownloaderPlus with set parameters
    """
    type = "video-downloader-tiktok"  # job type ID
    category = "Visual"  # category
    title = "Download TikTok videos"  # title displayed in UI
    description = "Downloads full videos for TikTok"
    extension = "zip"
    media_type = "video"

    # coarse map spec; is_compatible_with (below) is the runtime truth -- it also accepts
    # tiktok uploads, which depends on the dataset label and can't be declared statically
    compatibility = Compatibility(type_prefixes={"tiktok-"}, top_dataset_only=True, preferred_followups=VideoDownloaderPlus.followups)

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
        """
        Get processor options

        :param config:
        :param DataSet parent_dataset:  Dataset that will be uploaded
        """
        options = {
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "help": "No. of videos (max 1000)",
                "default": 100,
                "min": 0,
                "max": 1000,
                "tooltip": "Due to simultaneous downloads, you may end up with a few extra videos."
            },
        }

        # Update the amount max and help from config
        max_number_videos = int(config.get('video-downloader.max', 1000))
        options['amount']['max'] = max_number_videos
        options['amount']['help'] = f"No. of videos (max {max_number_videos:,})"

        if parent_dataset:
            # This will be a special case
            if parent_dataset.type == "upload-search":
                options["column"] = {
                    "type": UserInput.OPTION_CHOICE,
                    "help": "Column with TikTok Post IDs (not video URLs)",
                    "options": {column: column for column in parent_dataset.get_columns()},
                    "default": "id"
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

    def get_processor_pipeline(self):
        """
        This queues the video-downloader with set options
        """
        amount = self.parameters.get("amount")

        metadata_parameters = {
            "amount": amount,
            "_amount_leeway": 10  # extra metadata in case videos fail
        }
        # only an uploaded dataset needs to be told which column holds the post
        # IDs; for TikTok datasources the metadata processor uses a fixed column
        if self.source_dataset.type == "upload-search":
            metadata_parameters["id_column"] = self.parameters.get("column")

        pipeline = [
            {
                "type": "tiktok-video-downloader-metadata",
                "parameters": metadata_parameters
            },
            {
                "type": "video-downloader",
                "parameters": {
                    "amount": amount,
                    "columns": ["video_url"],
                    "also_indirect": "all", # enabled YT-DLP
                    "_ytdlp_fallback_column": "tiktok_url" # YT-DLP uses TikTok post URL
                }
            },
        ]

        return pipeline

    @staticmethod
    def map_metadata(url, data):
        """
        Iterator to yield modified metadata for CSV

        The archive this preset produces is written by the video downloader in
        its pipeline and copied to this dataset, so the metadata file inside it
        has the video downloader's format and is read the same way.

        :param str url:  string that may contain URLs
        :param dict data:  dictionary with metadata collected previously
        :yield dict:  	  iterator containing reformated metadata
        """
        yield from VideoDownloaderPlus.map_metadata(url, data)


class TikTokVideoMetadata(BasicProcessor):
    """
    Helper dataset to update the video URLs for direct download; this is helpful to allow for proxied/simultaneous 
    requests to download videos. Otherwise all videos would be sent to YT-DLP (not currently asynchronous).
    """
    type = "tiktok-video-downloader-metadata"  # job type ID
    category = "Visual"  # category
    title = "TikTok Video URLs Updater"  # title displayed in UI
    description = "Retrieves updated video URLs from TikTok"
    extension = "csv"
    media_type = "text"

    consecutive_failures = None
    # one failure is often a single broken or removed post, but this many in a
    # row means TikTok is refusing our requests, so stop asking
    max_consecutive_failures = 10

    # internal helper dataset; never offered as a processor
    compatibility = Compatibility(types=set())

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
        """
        Get processor options

        :param config:
        :param DataSet parent_dataset:  Dataset that will be uploaded
        """
        options = {
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "help": "No. of videos (max 1000)",
                "default": 100,
                "min": 0,
                "max": 1000,
                "tooltip": "Due to simultaneous downloads, you may end up with a few extra videos."
            },
        }

        # Update the amount max and help from config
        max_number_videos = int(config.get('video-downloader.max', 1000))
        options['amount']['max'] = max_number_videos
        options['amount']['help'] = f"No. of videos (max {max_number_videos:,})"

        if parent_dataset:
            # This will be a special case
            if parent_dataset.type == "upload-search":
                options["id_column"] = {
                    "type": UserInput.OPTION_CHOICE,
                    "help": "Column with TikTok Post IDs (not video URLs)",
                    "options": {column: column for column in parent_dataset.get_columns()},
                    "default": "id"
                }
                options["url_column"] = {
                    "type": UserInput.OPTION_CHOICE,
                    "help": "Column with TikTok Post URL (not video URLs)",
                    "options": {column: column for column in parent_dataset.get_columns()},
                    "default": "tiktok_url"
                }

        return options

    def process(self):
        if self.source_dataset.num_rows == 0:
            self.dataset.finish_as_empty("No videos to download.")
            return

        # Process parameters
        amount = self.parameters.get("amount") if self.parameters.get("amount") != 0 else self.source_dataset.num_rows
        _amount_leeway = self.parameters.get("_amount_leeway", 0)
        max_amount = min(amount + _amount_leeway, self.source_dataset.num_rows)
        if self.source_dataset.type == "upload-search":
            # Variable column name
            column = self.parameters.get("id_column")
            tiktok_url_column = self.parameters.get("url_column")
        else:
            column = "id"
            tiktok_url_column = "tiktok_url"

        metadata_urls = {}
        image_posts = 0
        for mapped_item in self.source_dataset.iterate_items(self):
            post_id = mapped_item.get(column)
            if not post_id:
                continue
            if mapped_item.get("is_image_post") == "yes":
                image_posts += 1
                continue
            try:
                # Test post ID is an integer (as TikTok post IDs ought to be)
                int(post_id)
            except ValueError:
                self.dataset.finish_with_error(f"Column {column} must contain TikTok post IDs")
                return
            
            # Get TikTok post URL for YT-DLP
            tiktok_url = mapped_item.get(tiktok_url_column, "")

            # Double-check: don't get photo posts (should already be skipped)
            if "/photo/" in tiktok_url:
                continue
            
            metadata_urls[f"https://www.tiktok.com/embed/v2/{post_id}"] = {
                "id": post_id,
                "tiktok_url": tiktok_url
            }

        if not metadata_urls:
            self.dataset.finish_as_empty("No video URLs found for this dataset; all posts are likely images.")
            self.job.finish()
            return
        if image_posts:
            self.dataset.update_status(f"Skipping {image_posts} image posts.")

        with self.dataset.get_results_path().open("w", newline="") as outfile:
            writer = csv.DictWriter(outfile, fieldnames=["id", "tiktok_url", "video_url", "errors", "fallback_only"])
            writer.writeheader()

            urls_success = 0
            self.urls_failed = 0
            self.consecutive_failures = 0
            total_processed = 0
            posts_unavailable = 0
            forced_stop = False
            for url, response in self.iterate_proxied_requests(
                    list(metadata_urls),
                    preserve_order=True,
                    headers=TikTokScraper.headers,
                    timeout=20,
                ):
                if self.interrupted:
                    # If interrupted, break loop and finish with warning (to save progress)
                    # Note we always flush after the loop, so any remaining requests are cancelled and not sent to TikTok
                    break

                video_id = metadata_urls[url]["id"]
                tiktok_url = metadata_urls[url]["tiktok_url"]
                item_result = {
                    "id": video_id,
                    "tiktok_url": tiktok_url,
                    "errors": [],
                    "fallback_only": False
                }
                if isinstance(response, FailedProxiedRequest):
                    forced_stop = self._track_failures(f"Failed to retrieve URL {url} ({response.context})", item_result)
                else:
                    video_metadata = self._get_embedded_metadata(response, video_id)
                    post_data = self._get_post_data(video_metadata)

                    if not video_metadata:
                        # e.g. TikTok refused us, checks if we are human, or now builds the page differently
                        forced_stop = self._track_failures(f"TikTok sent a page without video metadata for video {video_id}", item_result,
                                                           details=self._describe_response(response))
                    elif post_data.get("isError"):
                        # TikTok answered as usual, but has no video for this post. This still
                        # counts towards stopping, in case TikTok quietly refuses us this way
                        posts_unavailable += 1
                        forced_stop = self._track_failures(f"TikTok says video {video_id} is not available, for example because it was removed "
                                                           f"(TikTok error code {post_data.get('errorCode', 'unknown')}, HTTP {response.status_code})", item_result)
                    elif response.status_code != 200:
                        forced_stop = self._track_failures(f"TikTok answered HTTP {response.status_code} for video {video_id}", item_result,
                                                           details=self._describe_response(response))
                    else:
                        try:
                            item_result["video_url"] = post_data["videoData"]["itemInfos"]["video"]["urls"][0]
                            # Reset consecutive failures on success
                            self.consecutive_failures = 0
                            urls_success += 1
                        except (KeyError, IndexError, TypeError):
                            # TypeError: TikTok sent null or another type where we expect data
                            forced_stop = self._track_failures(f"Failed to find video download URL for video {video_id}", item_result, video_metadata)

                # Write record
                writer.writerow(item_result)
                total_processed += 1
                self.dataset.update_status("Collected metadata for %i/%i videos" %
                                                (urls_success, max_amount))
                self.dataset.update_progress(urls_success / max_amount)
                # Give some leeway on max_amount as videos themselves may fail in next processor
                if urls_success >= max_amount:
                    break
                elif forced_stop:
                    self.dataset.update_status(f"Stopped after {self.consecutive_failures} failed requests in a row ({urls_success} succeeded before that)")
                    break

            # cancel requests that are still queued (we may have stopped early), so TikTok is not asked for more
            self.flush_proxied_requests()

        # removed posts are not TikTok refusing us, so say how many of the failures they are
        unavailable_note = f" For {posts_unavailable} of these, TikTok says the post is not available, for example because it was removed." if posts_unavailable else ""
        if forced_stop:
            if urls_success == 0:
                self.dataset.finish_with_error(f"TikTok did not give a video URL for any of the first {total_processed} posts, so 4CAT stopped asking.{unavailable_note} See the dataset log for what TikTok sent back.")
            else:
                self.dataset.finish_with_warning(total_processed, f"Stopped after {self.consecutive_failures} failed requests in a row, with video URLs for {urls_success} posts collected.{unavailable_note} See the dataset log for what TikTok sent back.")
        elif self.interrupted:
            self.dataset.finish_with_warning(total_processed, f"Interrupted after collecting video URLs for {urls_success} posts.")
        elif self.urls_failed > 0:
            self.dataset.finish_with_warning(total_processed, f"Collected video URLs for {urls_success} posts. {self.urls_failed} did not have valid video URLs.{unavailable_note} See the dataset log for details.")
        else:
            self.dataset.finish(total_processed)
            self.job.finish()

    def _track_failures(self, error_message, item_result, video_metadata=None, details=None):
        """
        Record a failed post and decide whether to keep going

        :param str error_message:  Short error, saved with the post and logged
        :param dict item_result:  Row for this post, updated in place
        :param dict video_metadata:  Metadata TikTok sent, if any, to log
        :param str details:  Longer description for the log only
        :return bool:  True if there were too many failures in a row to go on
        """
        # Update item_result with failure info and log
        item_result["errors"].append(error_message)
        item_result["video_url"] = None
        item_result["fallback_only"] = True
        self.dataset.log(f"{error_message} ({details})" if details else error_message)
        if video_metadata:
            # the metadata may not have the shape we expect; that may be why we are here
            try:
                self.dataset.log(video_metadata["source"]["data"].values())
            except (KeyError, TypeError, AttributeError):
                self.dataset.log(video_metadata)

        # Count failure and evaluate thresholds
        self.urls_failed += 1
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.max_consecutive_failures:
            self.dataset.update_status("Too many consecutive failures, stopping")
            return True
        return False

    def _get_embedded_metadata(self, response, video_id):
        """
        Get the video metadata TikTok puts in the embed page as JSON

        :param requests.Response response:  Embed page from TikTok
        :param str video_id:  Post ID, for the log
        :return dict|None:  Metadata, or None if the page does not have it
        """
        soup = BeautifulSoup(response.text, "html.parser")
        json_source = soup.select_one("script#__FRONTITY_CONNECT_STATE__")
        if not json_source:
            return None

        json_text = json_source.text or (json_source.contents[0] if json_source.contents else "")
        if not json_text:
            return None

        try:
            return json.loads(json_text)
        except json.JSONDecodeError as e:
            self.dataset.log(f"JSONDecodeError for video {video_id} metadata: {e}\n{json_source}")
            return None

    @staticmethod
    def _get_post_data(video_metadata):
        """
        Get the part of the embed page metadata that is about the post

        This holds the video data, or, if TikTok has no video for the post,
        `isError` and TikTok's own `errorCode`.

        :param dict|None video_metadata:  Metadata from the embed page
        :return dict:  Data about the post, empty if it cannot be found
        """
        try:
            post_data = list(video_metadata["source"]["data"].values())[0]
        except (KeyError, IndexError, TypeError, AttributeError):
            return {}

        return post_data if isinstance(post_data, dict) else {}

    @staticmethod
    def _describe_response(response):
        """
        Describe a TikTok response that is not the page we expected

        This goes in the dataset log, to show whether TikTok refused the
        request, sent us somewhere else, or sent a different page.

        :param requests.Response response:  Response from TikTok
        :return str:  Short description
        """
        details = [f"HTTP {response.status_code} {response.reason or ''}".strip()]
        if response.history:
            redirects = ", ".join(str(earlier.status_code) for earlier in response.history)
            details.append(f"redirected ({redirects}) to {response.url}")
        if response.headers.get("Retry-After"):
            details.append(f"asked to retry after {response.headers['Retry-After']}")
        details.append(f"{len(response.content):,} bytes of {response.headers.get('Content-Type', 'unknown type')}")

        page = BeautifulSoup(response.text, "html.parser")
        if page.title and page.title.get_text(strip=True):
            details.append(f"page title: {page.title.get_text(strip=True)}")
        # if TikTok moved the metadata to another script tag, this shows where
        script_ids = [script["id"] for script in page.find_all("script", id=True)]
        details.append(f"script ids on page: {', '.join(script_ids) if script_ids else 'none'}")
        text = " ".join(page.get_text(" ").split())
        if text:
            details.append(f"page text starts: {text[:300]}")

        return "; ".join(details)
