"""
Download images from Telegram message attachments
"""
import asyncio
import hashlib
import json

from pathlib import Path

from telethon import TelegramClient

import config

from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.helpers import UserInput
from common.lib.dataset import DataSet

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class TelegramImageDownloader(BasicProcessor):
    """
    Telegram image downloader

    Downloads attached images from Telegram messages and saves as zip archive
    """
    type = "image-downloader-telegram"  # job type ID
    category = "Visual"  # category
    title = "Download Telegram images"  # title displayed in UI
    description = "Download images and store in a zip file. Downloads through the Telegram API might take a while. " \
                  "Note that not always all images can be retrieved. A JSON metadata file is included in the output " \
                  "archive."  # description displayed in UI
    extension = "zip"  # extension of result file, used internally and in UI

    max_number_images = int(config.MAX_NUMBER_IMAGES) if hasattr(config, 'MAX_NUMBER_IMAGES') else 1000
    flawless = True

    options = {
        "amount": {
            "type": UserInput.OPTION_TEXT,
            "help": "No. of images (max %s)" % max_number_images,
            "default": 100,
            "min": 0,
            "max": max_number_images
        },
        "video-thumbnails": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Include videos (as thumbnails)",
            "default": False
        }
    }

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Allow processor on Telegram datasets with required info

        :param module: Dataset or processor to determine compatibility with
        """
        if type(module) is DataSet:
            # we need these to actually instantiate a telegram client and
            # download the images
            return module.type == "telegram-search" and \
                   "api_phone" in module.parameters and \
                   "api_id" in module.parameters and \
                   "api_hash" in module.parameters
        else:
            return module.type == "telegram-search"

    def process(self):
        """
        Prepare and asynchronously call method to download images
        """
        self.staging_area = self.dataset.get_staging_area()
        self.eventloop = None
        self.metadata = {}

        asyncio.run(self.get_images())

        # finish up
        with self.staging_area.joinpath(".metadata.json").open("w", encoding="utf-8") as outfile:
            json.dump(self.metadata, outfile)

        self.dataset.update_status("Compressing images")
        self.write_archive_and_finish(self.staging_area)

    async def get_images(self):
        """
        Get images for messages

        Separate method because this needs to be run asynchronously. Looks for
        messages in the dataset with photo attachments, then loads those
        messages from the client, then downloads the attachments of those
        messages and saves them as .jpeg files.
        """
        # prepare telegram client parameters
        query = self.source_dataset.top_parent().parameters
        hash_base = query["api_phone"].replace("+", "") + query["api_id"] + query["api_hash"]
        session_id = hashlib.blake2b(hash_base.encode("ascii")).hexdigest()
        session_path = Path(config.PATH_ROOT).joinpath(config.PATH_SESSIONS, session_id + ".session")
        amount = self.parameters.get("amount")
        with_thumbnails = self.parameters.get("video-thumbnails")
        client = None

        # we need a session file, otherwise we can't retrieve the necessary data
        if not session_path.exists():
            self.dataset.update_status("Telegram session file missing. Cannot download images.", is_final=True)
            return []

        # instantiate client
        try:
            client = TelegramClient(str(session_path), int(query.get("api_id")), query.get("api_hash"),
                                    loop=self.eventloop)
            await client.start(phone=TelegramImageDownloader.cancel_start)
        except RuntimeError:
            # session is no longer usable
            self.dataset.update_status(
                "Session is not authenticated: login security code may have expired. You need to  create a new "
                "dataset to download images from and re-enter the security code", is_final=True)

        # figure out which messages from the dataset we need to download media
        # for. Right now, that's everything with a non-empty `photo` attachment
        # or `video` if we're also including thumbnails
        messages_with_photos = {}
        downloadable_types = ("photo",) if not with_thumbnails else ("photo", "video")
        total_media = 0
        self.dataset.update_status("Finding messages with image attachments")
        for message in self.source_dataset.iterate_items(self):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while processing messages")

            if not message.get("attachment_data") or message.get("attachment_type") not in downloadable_types:
                continue

            if message["chat"] not in messages_with_photos:
                messages_with_photos[message["chat"]] = []

            messages_with_photos[message["chat"]].append(int(message["id"]))
            total_media += 1

            if amount and total_media >= amount:
                break

        # now actually download the images
        # todo: investigate if we can directly instantiate a MessageMediaPhoto instead of fetching messages
        media_done = 1
        for entity, message_ids in messages_with_photos.items():
            async for message in client.iter_messages(entity=entity, ids=message_ids):
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while downloading images")

                success = False
                try:
                    # it's actually unclear if images are always jpegs, but this
                    # seems to work
                    self.dataset.update_status("Downloading media %i/%i" % (media_done, total_media))
                    path = self.staging_area.joinpath("%s-%i.jpeg" % (entity, message.id))
                    filename = path.name
                    if hasattr(message.media, "photo"):
                        await message.download_media(str(path))
                    else:
                        # video thumbnail
                        await client.download_media(message, str(path), thumb=-1)
                    msg_id = message.id
                    success = True
                except (AttributeError, RuntimeError, ValueError, TypeError) as e:
                    filename = "%s-index-%i" % (entity, media_done)
                    msg_id = str(message.id) if hasattr(message, "id") else "with index %i" % media_done
                    self.dataset.log("Could not download image for message %s (%s)" % (msg_id, str(e)))
                    self.flawless = False

                media_done += 1
                self.metadata[filename] = {
                    "filename": filename,
                    "success": success,
                    "from_dataset": self.source_dataset.key,
                    "post_ids": [msg_id]
                }

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

    @classmethod
    def get_options(cls=None, parent_dataset=None, user=None):
        """
        Get processor options

        This method by default returns the class's "options" attribute, but
        will lift the limit on the amount of images collected from Telegram
        user requesting the options has been configured as such.

        :param DataSet parent_dataset:  An object representing the dataset that
        the processor would be run on
        :param User user:  Flask user the options will be displayed for, in
        case they are requested for display in the 4CAT web interface. This can
        be used to show some options only to privileges users.
        """
        options = cls.options.copy()

        if user and user.get_value("telegram.can_query_all_messages", False):
            if "max" in options["amount"]:
                del options["amount"]["max"]

        return options
