"""
Refresh a TikTok datasource
"""
import asyncio
import datetime
import json
from io import BytesIO
from pathlib import Path
from PIL import Image, UnidentifiedImageError
from urllib.parse import urlparse, parse_qs
import requests

from common.lib.exceptions import ProcessorInterruptedException
from common.lib.user_input import UserInput
from datasources.tiktok_urls.search_tiktok_urls import TikTokScraper, RepeatedFailure
from processors.visualisation.download_videos import VideoDownloaderPlus
from datasources.tiktok.search_tiktok import SearchTikTok as SearchTikTokByImport
from processors.visualisation.download_images import ImageDownloader
from backend.lib.processor import BasicProcessor


__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class TikTokVideoDownloader(BasicProcessor):
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

        This method by default returns the class's "options" attribute, or an
        empty dictionary. It can be redefined by processors that need more
        fine-grained options, e.g. in cases where the availability of options
        is partially determined by the parent dataset's parameters.

        :param config:
        :param DataSet parent_dataset:  An object representing the dataset that
        the processor would be run on can be used to show some options only to
        privileges users.
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

    def process(self):
        """
        Reads a file, filtering items that match in the required way, and
        creates a new dataset containing the matching values
        """
        if self.source_dataset.num_rows == 0:
            self.dataset.finish_as_empty("No videos to download.")
            return

        # Process parameters
        amount = self.parameters.get("amount") if self.parameters.get("amount") != 0 else self.source_dataset.num_rows
        max_amount = min(amount, self.source_dataset.num_rows)
        if self.source_dataset.type == "upload-search":
            # Variable column name
            column = self.parameters.get("column")
        else:
            column = "id"

        # Prepare staging area for downloads
        results_path = self.dataset.get_staging_area()

        self.dataset.update_status("Downloading TikTok media")
        video_ids_to_download = set()
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
            
            video_ids_to_download.add(post_id)

        # the downloader is an asynchronous method because we want to be able
        # to run multiple downloads in parallel

        tiktok_scraper = TikTokScraper(processor=self, config=self.config)
        loop = asyncio.new_event_loop()
        try:
            results = loop.run_until_complete(
                tiktok_scraper.download_videos(list(video_ids_to_download), results_path, max_amount)
            )
        except RepeatedFailure as e:
            if self.source_dataset.type == "upload-search":
                self.dataset.finish_with_error(f"TikTok video downloader failed repeatedly. Please check that the column '{column}' contains valid TikTok post IDs. Error: {e}")
            else:
                self.log.warning(f"TikTok video downloader ({self.dataset.key}) failed repeatedly; may be parsing issue: {e}")
                self.dataset.finish_with_error(f"TikTok video downloader failed repeatedly: {e}")
            return

        with results_path.joinpath(".metadata.json").open("w", encoding="utf-8") as outfile:
            json.dump(results, outfile)

        self.write_archive_and_finish(results_path, len([True for result in results.values() if result.get("success")]))

    @staticmethod
    def map_metadata(video_id, data):
        """
        Iterator to yield modified metadata for CSV

        :param str video_id:  string that may contain URLs
        :param dict data:  dictionary with metadata collected previously
        :yield dict:  	  iterator containing reformated metadata
        """
        # TODO: could provide additional metadata via video downloader, but need to map those fields
        filename = data.pop("files")[0].get("filename") if "files" in data else None
        row = {
            "video_id": video_id,
            "filename": filename,
            "success": data.get("success", "Metadata read error"),
            "url": data.get("url", "Metadata read error"),
            "error": data.get("error", "Metadata read error"),
            "from_dataset": data.get("from_dataset", "Metadata read error"),
            "post_ids": ", ".join(data.get("post_ids", ["Metadata read error"])),
        }
        yield row

class TikTokImageDownloader(BasicProcessor):
    type = "image-downloader-tiktok"  # job type ID
    category = "Visual"  # category
    title = "Download TikTok images"  # title displayed in UI
    description = "Downloads video/music thumbnails for TikTok; refreshes TikTok data if URLs have expired"
    extension = "zip"
    media_type = "image"

    followups = ImageDownloader.followups

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
        """
        Get processor options

        This method by default returns the class's "options" attribute, or an
        empty dictionary. It can be redefined by processors that need more
        fine-grained options, e.g. in cases where the availability of options
        is partially determined by the parent dataset's parameters.

        :param DataSet parent_dataset:  An object representing the dataset that
        the processor would be run on
        :param User user:  Flask user the options will be displayed for, in
        case they are requested for display in the 4CAT web interface. This can
        be used to show some options only to privileges users.
        """
        options = {
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "help": "No. of items (max 1000)",
                "default": 100,
                "min": 0,
                "max": 1000
            },
            "thumb_type": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Media type",
                "options": {
                    "thumbnail": "Video Thumbnail",
                    "music": "Music Thumbnail",
                    "author_avatar": "User avatar"
                },
                "default": "thumbnail"
            }
        }

        # Update the amount max, min, tooltip, and help from config
        max_number_images = int(config.get("image-downloader.max", 1000))
        if max_number_images == 0:
            options['amount']['tooltip'] = "'0' will use all available images"
            options['amount'].pop('max') if 'max' in options['amount'] else None
            options['amount']['help'] = "No. of images"
        else:
            options['amount']['help'] = f"No. of images (max {max_number_images:,})"
            options['amount']['max'] = max_number_images
            options["amount"]["min"] = 1

        return options

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Allow processor TikTok datasets

        :param module: Dataset or processor to determine compatibility with
        :param ConfigManager config:  Configuration reader (context-aware)
        """
        return module.type in ["tiktok-search", "tiktok-urls-search"]

    def process(self):
        """
        Reads a file, filtering items that match in the required way, and
        creates a new dataset containing the matching values
        """
        if self.source_dataset.num_rows == 0:
            self.dataset.finish_as_empty("No images to download.")
            return

        # Process parameters
        amount = self.parameters.get("amount") if self.parameters.get("amount") != 0 else self.source_dataset.num_rows
        max_amount = min(amount, self.source_dataset.num_rows)
        if self.parameters.get("thumb_type") == "thumbnail":
            url_column = "thumbnail_url"
        elif self.parameters.get("thumb_type") == "music":
            url_column = "music_thumbnail"
        elif self.parameters.get("thumb_type") == "author_avatar":
            url_column = "author_avatar"
        else:
            self.dataset.finish_with_error("No image column selected.")
            return

        # Prepare staging area for downloads
        results_path = self.dataset.get_staging_area()

        self.dataset.update_status("Downloading TikTok media")
        downloaded_media = 0
        urls_to_refresh = []
        url_to_item_id = {}
        max_fails_exceeded = 0
        metadata = {}

        # Loop through items and collect URLs
        for mapped_item in self.source_dataset.iterate_items(self):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while downloading TikTok images")

            if downloaded_media >= max_amount:
                break

            url = mapped_item.get(url_column)
            post_id = mapped_item.get("id")

            if max_fails_exceeded > 4:
                # Let's just refresh remaining URLs if it is clear the dataset is old
                refresh_tiktok_urls = True
            else:
                refresh_tiktok_urls = False

                # Check if URL missing or expired
                now = int(datetime.datetime.now(tz=datetime.timezone.utc).timestamp())
                if not url or int(parse_qs(urlparse(url).query).get("x-expires", [now])[0]) < now:
                    refresh_tiktok_urls = True
                else:
                    # Collect image
                    try:
                        image, extension = self.collect_image(url)
                        success, filename = self.save_image(image, mapped_item.get("id") + "." + extension, results_path)
                    except FileNotFoundError as e:
                        self.dataset.log(f"{e} for {url}, refreshing")
                        success = False
                        filename = ''

                    if not success:
                        # Add TikTok post to be refreshed
                        refresh_tiktok_urls = True
                        # Stop checking and refresh all remaining URLs
                        max_fails_exceeded += 1
                    else:
                        self.dataset.update_status(f"Downloaded image for {url}")
                        downloaded_media += 1

                        metadata[url] = {
                                "filename": filename,
                                "success": success,
                                "from_dataset": self.source_dataset.key,
                                "post_ids": [post_id]
                        }


            if refresh_tiktok_urls:
                # Add URL to later refresh TikTok data
                tiktok_url = mapped_item.get("tiktok_url")
                if tiktok_url in url_to_item_id:
                    url_to_item_id[tiktok_url].append(mapped_item.get("id"))
                else:
                    urls_to_refresh.append(tiktok_url)
                    url_to_item_id[tiktok_url] = [mapped_item.get("id")]

        if downloaded_media < max_amount and urls_to_refresh:
            # Refresh and collect more images
            tiktok_scraper = TikTokScraper(processor=self, config=self.config)
            need_more = max_amount - downloaded_media
            last_url_index = 0
            while need_more > 0:
                url_slice = urls_to_refresh[last_url_index: last_url_index + need_more]
                if len(url_slice) == 0:
                    # Ensure there are still URLs to process
                    break
                self.dataset.update_status(f"Refreshing {len(url_slice)} TikTok posts")
                loop = asyncio.new_event_loop()
                # Refresh only number of URLs needed to complete image downloads
                refreshed_items = loop.run_until_complete(tiktok_scraper.request_metadata(url_slice))
                self.dataset.update_status(f"Refreshed {len(refreshed_items)} TikTok posts")

                for refreshed_item in refreshed_items:
                    if self.interrupted:
                        raise ProcessorInterruptedException("Interrupted while downloading TikTok images")

                    refreshed_mapped_item = SearchTikTokByImport.map_item(refreshed_item)
                    if refreshed_mapped_item.get_missing_fields():
                        self.dataset.log(f"The following fields were missing in item and have been replaced with a "
                                         f"default value: {', '.join(refreshed_mapped_item.get_missing_fields())}")

                    refreshed_mapped_item = refreshed_mapped_item.get_item_data(safe=True)
                    post_id = refreshed_mapped_item.get("id")
                    url = refreshed_mapped_item.get(url_column)

                    if not url:
                        # Unable to request and save image
                        success = False
                        filename = ''
                    else:
                        # Collect image
                        try:
                            image, extension = self.collect_image(url)
                            success, filename = self.save_image(image, post_id + "." + extension, results_path)
                        except FileNotFoundError as e:
                            self.dataset.log(f"Error with {url}: {e}")
                            success = False
                            filename = ''

                    # Record metadata
                    metadata[url] = {
                            "filename": filename,
                            "success": success,
                            "from_dataset": self.source_dataset.key,
                            "post_ids": [post_id]
                    }

                    if success:
                        self.dataset.update_status(f"Downloaded image for {url}")
                        downloaded_media += 1
                    elif not url:
                        self.dataset.log(
                            f"No {url_column} identified for {refreshed_mapped_item.get('tiktok_url')}, skipping")
                    else:
                        self.dataset.log(f"Unable to save image for {url}, skipping")

                # In case some images failed to download, we update our starting points
                last_url_index += need_more
                need_more = max_amount - downloaded_media

        # Write metadata file
        with results_path.joinpath(".metadata.json").open("w", encoding="utf-8") as outfile:
            json.dump(metadata, outfile)

        self.write_archive_and_finish(results_path, downloaded_media)

    @staticmethod
    def save_image(image, image_name, directory_path):
        """
        Save image as image_name to directory_path

        :param Image image:         Opened image object to be saved
        :param str image_name:      Filename for image
        :param Path directory_path: Path where image should be saved
        :return bool, str:          True if saved successfully, False otherwise; and str of filename
        """
        try:
            image.save(str(directory_path.joinpath(image_name)))
            return True, image_name
        except OSError:
            # Some images may need to be converted to RGB to be saved
            try:
                picture = image.convert('RGB')
                image_name = Path(image_name).with_suffix(".png")
                picture.save(str(directory_path.joinpath(image_name)))
                return True, str(image_name)
            except OSError:
                return False, ''
        except ValueError:
            return False, ''

    @staticmethod
    def collect_image(url, user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/12.1.1 Safari/605.1.15"):
        """
        :param str url:         String with a validated URL
        :param str user_agent:  String with the desired user agent to be sent as a header
        """
        try:
            response = requests.get(url, stream=True, timeout=20, headers={"User-Agent": user_agent})

            if response.status_code != 200 or "image" not in response.headers.get("content-type", ""):
                raise FileNotFoundError(f"Unable to download image; status_code:{response.status_code} content-type:{response.headers.get('content-type', '')}")

            # Process images
            image_io = BytesIO(response.content)
            try:
                picture = Image.open(image_io)
            except UnidentifiedImageError:
                picture = Image.open(image_io.raw)
        except (ConnectionError, requests.exceptions.RequestException) as e:
            raise FileNotFoundError(f"Unable to download TikTok image via {url} ({e}), skipping")

        # Grab extension from response
        extension = response.headers["Content-Type"].split("/")[-1]

        return picture, extension

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
            "filename": data.get("filename"),
            "download_successful": data.get('success', "")
        }

        yield row
