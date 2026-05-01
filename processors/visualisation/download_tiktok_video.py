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

    followups = VideoDownloaderPlus.followups

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
        return module.type in ["tiktok-search", "tiktok-urls-search"] or (module.type == "upload-search" and "tiktok" in module.get_label().lower())

    def get_processor_pipeline(self):
        """
        This queues the video-downloader with set options
        """
        # Check if an upload
        if self.source_dataset.type == "upload-search":
            # Variable column name
            column = self.parameters.get("column")
        else:
            column = "id"

        amount = self.parameters.get("amount")

        pipeline = [
            {
                "type": "tiktok-video-downloader-metadata",
                "parameters": {
                    "column": column,
                    "amount": amount,
                    "_amount_leeway": 10 # extra metadata in case videos fail
                }
            },
            {
                "type": "video-downloader",
                "parameters": {
                    "amount": amount,
                    "columns": ["video_url"],
                    "split-comma": False,
                    "also_indirect": "all", # enabled YT-DLP
                    "_ytdlp_fallback_column": "tiktok_url" # YT-DLP uses TikTok post URL
                }
            },
        ]

        return pipeline


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

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Do not show anywhere
        """
        return False
    
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
        for mapped_item in self.source_dataset.iterate_items(self):
            post_id = mapped_item.get(column)
            if not post_id:
                continue
            try:
                # Test post ID is an integer (as TikTok post IDs ought to be)
                int(post_id)
            except ValueError:
                self.dataset.finish_with_error(f"Column {column} must contain TikTok post IDs")
                return
            
            # Get TikTok post URL for YT-DLP
            tiktok_url = mapped_item.get(tiktok_url_column, "")
            
            metadata_urls[f"https://www.tiktok.com/embed/v2/{post_id}"] = {
                "id": post_id,
                "tiktok_url": tiktok_url
            } 

        with self.dataset.get_results_path().open("w", newline="") as outfile:
            writer = csv.DictWriter(outfile, fieldnames=["id", "tiktok_url", "video_url", "errors", "fallback_only"])
            writer.writeheader()

            urls_success = 0
            self.urls_failed = 0
            self.consecutive_failures = 0
            total_processed = 0
            forced_stop = False
            for url, response in self.iterate_proxied_requests(
                    list(metadata_urls),
                    preserve_order=True,
                    headers=TikTokScraper.headers,
                    timeout=20,
                ):
                if self.interrupted:
                    # If interrupted, break loop and finish with warning (to save progress)
                    self.flush_proxied_requests()
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
                    # Collect Video Download URL
                    soup = BeautifulSoup(response.text, "html.parser")
                    json_source = soup.select_one("script#__FRONTITY_CONNECT_STATE__")
                    video_metadata = None
                    try:
                        if json_source.text:
                            video_metadata = json.loads(json_source.text)
                        elif json_source.contents[0]:
                            video_metadata = json.loads(json_source.contents[0])
                    except json.JSONDecodeError as e:
                        self.dataset.log(f"JSONDecodeError for video {video_id} metadata: {e}\n{json_source}")

                    if not video_metadata:
                        # Failed to collect metadata
                        forced_stop = self._track_failures(f"Failed to find metadata for video {video_id}", item_result)
                    else:
                        try:
                            item_result["video_url"] = list(video_metadata["source"]["data"].values())[0]["videoData"]["itemInfos"]["video"]["urls"][0]
                            # Reset consecutive failures on success
                            self.consecutive_failures = 0
                            urls_success += 1
                        except (KeyError, IndexError):
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
                    self.dataset.update_status("Stopped collecting video URLs after %i successes due to too many consecutive failures" % urls_success)
                    break

        if forced_stop:
            self.dataset.finish_with_warning(total_processed, f"Unable to continue after {urls_success} urls; see logs for details")
        elif self.interrupted:
            self.dataset.finish_with_warning(total_processed, f"Interrupted after collecting Video URLs for {urls_success} posts.")
        elif self.urls_failed > 0:
            self.dataset.finish_with_warning(total_processed, f"Collected Video URLs for {urls_success} posts. {self.urls_failed} did not have valid video URLs; see logs for details")
        else:
            self.dataset.finish(total_processed)
            self.job.finish()

    def _track_failures(self, error_message, item_result, video_metadata=None):
        # Update item_result with failure info and log
        item_result["errors"].append(error_message)
        item_result["video_url"] = None
        item_result["fallback_only"] = True
        self.dataset.log(error_message)
        if video_metadata:
            self.dataset.log(video_metadata["source"]["data"].values())

        # Count failure and evaluate thresholds
        self.urls_failed += 1
        self.consecutive_failures += 1
        if self.consecutive_failures >= 10:
            self.dataset.update_status("Too many consecutive failtures, stopping")
            return True
        return False