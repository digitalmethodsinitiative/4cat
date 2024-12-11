"""
Download videos from Telegram message attachments
"""
import asyncio
import hashlib
import json

from pathlib import Path

from telethon import TelegramClient
from telethon.errors import FloodError, BadRequestError

from common.config_manager import config
from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException
from processors.visualisation.download_videos import VideoDownloaderPlus
from common.lib.helpers import UserInput, timify_long
from common.lib.dataset import DataSet

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class TelegramVideoDownloader(BasicProcessor):
    """
    Telegram video downloader

    Downloads attached videos from Telegram messages and saves as zip archive
    """
    type = "video-downloader-telegram"  # job type ID
    category = "Visual"  # category
    title = "Download Telegram videos"  # title displayed in UI
    description = "Download videos and store in a zip file. Downloads through the Telegram API might take a while. " \
                  "Note that not always all videos can be retrieved. A JSON metadata file is included in the output " \
                  "archive."  # description displayed in UI
    extension = "zip"  # extension of result file, used internally and in UI
    media_type = "video"  # media type of the result
    flawless = True

    followups = VideoDownloaderPlus.followups

    config = {
        "video-downloader-telegram.max_videos": {
            "type": UserInput.OPTION_TEXT,
            "default": 100,
            "help": "Max videos",
            "tooltip": "Maxmimum number of Telegram videos a user can download.",
        },
        "video-downloader-telegram.allow_videos": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Allow video downloads",
            "tooltip": "Enable 'Download Telegram Videos' processor?",
        },
    }

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        Get processor options

        Give the user the choice of where to upload the dataset, if multiple
        TCAT servers are configured. Otherwise, no options are given since
        there is nothing to choose.

        :param DataSet parent_dataset:  Dataset that will be uploaded
        :param User user:  User that will be uploading it
        :return dict:  Option definition
        """
        max_videos = int(config.get('video-downloader-telegram.max_videos', 100, user=user))

        return {
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "help": f"Amount of videos (max {max_videos:,})",
                "default": 100,
                "min": 0,
                "max": max_videos
            }
        }


    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow processor on Telegram datasets with required info

        :param module: Dataset or processor to determine compatibility with
        """
        if not config.get("video-downloader-telegram.allow_videos", user=user):
            return False

        if type(module) is DataSet:
            # we need these to actually instantiate a telegram client and
            # download the videos
            return module.type == "telegram-search" and \
                   "api_phone" in module.parameters and \
                   "api_id" in module.parameters and \
                   "api_hash" in module.parameters
        else:
            return module.type == "telegram-search"

    def process(self):
        """
        Prepare and asynchronously call method to download videos
        """
        self.staging_area = self.dataset.get_staging_area()
        self.eventloop = None
        self.metadata = {}

        asyncio.run(self.get_videos())

        # finish up
        with self.staging_area.joinpath(".metadata.json").open("w", encoding="utf-8") as outfile:
            json.dump(self.metadata, outfile)

        self.dataset.update_status("Compressing videos")
        self.write_archive_and_finish(self.staging_area)

    async def get_videos(self):
        """
        Get videos for messages

        Separate method because this needs to be run asynchronously. Looks for
        messages in the dataset with photo attachments, then loads those
        messages from the client, then downloads the attachments of those
        messages and saves them as .jpeg files.
        """
        # prepare telegram client parameters
        query = self.source_dataset.top_parent().parameters
        hash_base = query["api_phone"].replace("+", "") + query["api_id"] + query["api_hash"]
        session_id = hashlib.blake2b(hash_base.encode("ascii")).hexdigest()
        session_path = Path(config.get('PATH_ROOT')).joinpath(config.get('PATH_SESSIONS'), session_id + ".session")
        amount = self.parameters.get("amount")

        client = None

        # we need a session file, otherwise we can't retrieve the necessary data
        if not session_path.exists():
            self.dataset.update_status("Telegram session file missing. Cannot download videos.", is_final=True)
            return []

        # instantiate client
        try:
            client = TelegramClient(str(session_path), int(query.get("api_id")), query.get("api_hash"),
                                    loop=self.eventloop)
            await client.start(phone=TelegramVideoDownloader.cancel_start)
        except RuntimeError:
            # session is no longer usable
            self.dataset.update_status(
                "Session is not authenticated: login security code may have expired. You need to create a new "
                "dataset to download videos from and re-enter the security code", is_final=True)

        # figure out which messages from the dataset we need to download media
        # for. Right now, that's everything with a non-empty `photo` attachment
        # or `video` if we're also including thumbnails
        messages_with_videos = {}
        downloadable_types = ["video"]

        total_media = 0
        self.dataset.update_status("Finding messages with video attachments")
        for message in self.source_dataset.iterate_items(self):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while processing messages")

            if not message.get("attachment_data") or message.get("attachment_type") not in downloadable_types:
                continue

            if message["chat"] not in messages_with_videos:
                messages_with_videos[message["chat"]] = []

            messages_with_videos[message["chat"]].append(int(message["id"].split("-")[-1]))
            total_media += 1

            if amount and total_media >= amount:
                break

        # now actually download the videos
        # todo: investigate if we can directly instantiate a MessageMediaPhoto instead of fetching messages
        media_done = 1
        for entity, message_ids in messages_with_videos.items():
            try:
                async for message in client.iter_messages(entity=entity, ids=message_ids):
                    if self.interrupted:
                        raise ProcessorInterruptedException("Interrupted while downloading videos")

                    success = False
                    try:
                        self.dataset.update_status(f"Downloading media {media_done:,}/{total_media:,}")
                        self.dataset.update_progress(media_done / total_media)

                        path = self.staging_area.joinpath(f"{entity}-{message.id}.mp4")
                        filename = path.name
                        if hasattr(message.media, "document"):
                            await message.download_media(str(path))

                        msg_id = message.id
                        success = True
                    except (AttributeError, RuntimeError, ValueError, TypeError, BadRequestError) as e:
                        filename = f"{entity}-index-{media_done}"
                        msg_id = str(message.id) if hasattr(message, "id") else f"with index {media_done:,}"
                        self.dataset.log(f"Could not download video for message {msg_id} ({e})")
                        self.flawless = False

                    media_done += 1
                    self.metadata[filename] = {
                        "filename": filename,
                        "success": success,
                        "from_dataset": self.source_dataset.key,
                        "post_ids": [msg_id]
                    }

            except FloodError as e:
                later = "later"
                if hasattr(e, "seconds"):
                    later = f"in {timify_long(e.seconds)}"
                self.dataset.update_status(f"Rate-limited by Telegram after downloading {media_done-1:,} image(s); "
                                           f"halting download process. Try again {later}.", is_final=True)
                self.flawless = False
                break
                    
            except ValueError as e:
                self.dataset.log(f"Couldn't retrieve video for {entity}, it probably does not exist anymore ({e})")
                self.flawless = False

    @staticmethod
    def cancel_start():
        """
        Replace interactive phone number input in Telethon

        By default, if Telethon cannot use the given session file to
        authenticate, it will interactively prompt the user for a phone
        number on the command line. That is not useful here, so instead
        raise a RuntimeError. This will be caught and the user will be
        told they need to re-authenticate via 4CAT.
        """
        raise RuntimeError("Connection cancelled")

    @staticmethod
    def map_metadata(filename, data):
        """
        Iterator to yield modified metadata for CSV

        :param str url:  string that may contain URLs
        :param dict data:  dictionary with metadata collected previously
        :yield dict:  	  iterator containing reformated metadata
        """
        row = {
            "number_of_posts_with_video": len(data.get("post_ids", [])),
            "post_ids": ", ".join(map(str, data.get("post_ids", []))),
            "filename": filename,
            "download_successful": data.get('success', "")
        }

        yield row
