"""
Download media (videos) from Telegram message attachments.

This module also serves as the base class for the image variant in
`download-telegram-images.py`. Subclasses override the protected
``_get_downloadable_types``, ``_can_download``, ``_download_to_path``, and
the ``_file_extension`` / ``_media_label`` / ``_metadata_count_label``
class attributes to switch behavior for a different media type.
"""
import asyncio
import hashlib
import json
import re
from collections import Counter

from telethon import TelegramClient
from telethon.errors import FloodError, BadRequestError

from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException
from datasources.telegram.search_telegram import SearchTelegram
from processors.visualisation.download_videos import VideoDownloaderPlus
from common.lib.helpers import UserInput, timify
from common.lib.dataset import DataSet

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters", "Dale Wahl"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class TelegramVideoDownloader(BasicProcessor):
    """
    Telegram video downloader

    Downloads attached videos from Telegram messages and saves as zip archive.
    Also serves as the base class for `TelegramImageDownloader`.
    """
    type = "video-downloader-telegram"  # job type ID
    category = "Visual"  # category
    title = "Download Telegram videos"  # title displayed in UI
    description = "Download videos and store in a ZIP file. Downloads through the Telegram API might take a while. " \
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

    # ---- subclass hooks ----
    # Subclasses override these to change file naming and CSV labelling.
    _file_extension = "mp4"
    _media_label = "video"
    _metadata_count_label = "number_of_posts_with_video"

    def _get_downloadable_types(self):
        """Which `attachment_type` values from the source dataset to pull."""
        return ["video"]

    def _can_download(self, message):
        """Whether the fetched message's media is something we can pass to download."""
        return hasattr(message.media, "document")

    def _get_file_extension(self, message):
        """Per-message file extension (without leading dot). Defaults to the
        class attribute; subclasses can override to derive from the message
        (e.g. file downloader uses the document MIME type)."""
        return self._file_extension

    def _get_filename(self, message, entity):
        """Build the output filename within the staging area.

        Default: ``{entity}-{message_id}.{extension}``. Subclasses can
        override (e.g. file downloader prefers the document's original
        filename from ``DocumentAttributeFilename``).
        """
        ext = self._get_file_extension(message)
        return f"{entity}-{message.id}.{ext}"

    async def _download_to_path(self, client, message, path):
        """Perform the actual file fetch; subclasses can switch on media variant."""
        await message.download_media(str(path))

    # ---- standard processor surface ----
    @classmethod
    def get_queue_id(cls, remote_id, details, dataset) -> str:
        """
        Queue ID: combining all Telethon downloaders to avoid "database is locked" 
        issues. May also combine with search_telegram if error still surfaces.

        TODO: investigate locking issue further
        """
        return "telegram-downloader"

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
        # 4CAT convention: admin sets the config to 0 to mean "unlimited".
        # In that mode the user can also enter 0 to actually fetch all items.
        max_videos = int(config.get('video-downloader-telegram.max_videos', 100))
        options = {
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "help": "Amount of videos" if max_videos == 0 else f"Amount of videos (max {max_videos:,})",
                "default": 100 if max_videos == 0 else min(100, max_videos),
                "min": 0 if max_videos == 0 else 1,
                "tooltip": "Maximum number of videos to download" + (
                    " (set to 0 to download all videos)" if max_videos == 0 else "")
            }
        }
        if max_videos != 0:
            options["amount"]["max"] = max_videos
        return options

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Allow processor on Telegram datasets with required info
        """
        if not config.get("video-downloader-telegram.allow_videos"):
            return False
        return cls._is_telegram_dataset(module)

    @classmethod
    def _is_telegram_dataset(cls, module):
        """Shared compatibility check: source dataset must be a telegram-search with API creds."""
        if type(module) is DataSet:
            return module.type == "telegram-search" and \
                   "api_phone" in module.parameters and \
                   "api_id" in module.parameters and \
                   "api_hash" in module.parameters
        else:
            return module.type == "telegram-search"

    def process(self):
        """
        Prepare and asynchronously call method to download media
        """
        self.staging_area = self.dataset.get_staging_area()
        self.eventloop = None
        self.metadata = {}
        self.reason_counts = Counter()

        asyncio.run(self.get_media())

        # finish up
        with self.staging_area.joinpath(".metadata.json").open("w", encoding="utf-8") as outfile:
            json.dump(self.metadata, outfile)

        self.dataset.update_status(f"Compressing {self._media_label}s")
        successful = self.reason_counts.get("ok", 0)
        warning = None
        if not self.flawless:
            total = sum(self.reason_counts.values())
            warning = (f"{successful:,} of {total:,} {self._media_label}(s) downloaded; "
                       "see dataset log for per-outcome breakdown.")
        # Pass num_items explicitly so the dataset's reported count matches the
        # number of *media files* downloaded (ignore .metadata.json)
        self.write_archive_and_finish(self.staging_area, num_items=successful, warning=warning)

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
    def categorize_download_error(exception):
        """
        Map a download exception to a (code, description) pair.

        Code is a short stable identifier suitable for metadata/CSV
        aggregation; description is the human-readable explanation written
        to the dataset log. Telegram raises errors with stable string
        identifiers, so we match on both class name and error string to
        avoid breaking if Telethon reshuffles its exception hierarchy.
        """
        err_name = type(exception).__name__
        err_str = str(exception)
        if err_name == "ChatForwardsRestrictedError" or "CHAT_FORWARDS_RESTRICTED" in err_str:
            return ("restricted_channel",
                    "Telegram refused the file fetch because the source channel has "
                    "'Restrict Saving Content' enabled. This is server-side enforcement "
                    "and cannot be bypassed by any client.")
        if err_name in ("FileReferenceExpiredError", "FileReferenceInvalidError") or "FILE_REFERENCE" in err_str:
            return ("file_reference_expired",
                    f"The file reference Telegram gave us is no longer valid ({err_name}); "
                    "re-running the downloader may help if the source message still exists.")
        if err_name == "MediaEmptyError" or "MEDIA_EMPTY" in err_str:
            return ("empty_media", "Telegram returned an empty media stub for this message.")
        return ("error", f"{err_name}: {exception}")

    async def get_media(self):
        """
        Download media for messages in the source dataset whose attachment
        matches the subclass's downloadable types. Runs asynchronously.
        """
        # prepare telegram client parameters
        query = self.source_dataset.top_parent().parameters
        hash_base = query["api_phone"].replace("+", "") + query["api_id"] + query["api_hash"]
        session_id = hashlib.blake2b(hash_base.encode("ascii")).hexdigest()
        session_path = self.config.get('PATH_SESSIONS').joinpath(session_id + ".session")
        amount = self.parameters.get("amount")

        client = None

        if not session_path.exists():
            self.dataset.update_status(
                f"Telegram session file missing. Cannot download {self._media_label}s.", is_final=True)
            return []

        try:
            client = TelegramClient(str(session_path), int(query.get("api_id")), query.get("api_hash"),
                                    loop=self.eventloop)
            await client.start(phone=self.cancel_start)
        except RuntimeError:
            self.dataset.update_status(
                "Session is not authenticated: login security code may have expired. You need to create a new "
                f"dataset to download {self._media_label}s from and re-enter the security code", is_final=True)
            return []

        downloadable_types = self._get_downloadable_types()
        messages_with_media = {}

        total_media = 0
        self.dataset.update_status(f"Finding messages with {self._media_label} attachments")
        for message in self.source_dataset.iterate_items(self):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while processing messages")

            if not message.get("attachment_data") or message.get("attachment_type") not in downloadable_types:
                continue

            if message["chat"] not in messages_with_media:
                messages_with_media[message["chat"]] = []

            messages_with_media[message["chat"]].append(int(message["id"].split("-")[-1]))
            total_media += 1

            if amount and total_media >= amount:
                break

        # Pre-warm Telethon's entity cache via the dialog list if any chat key
        # is a numeric ID. Private channels/groups (no @username) need their
        # access_hash cached before iter_messages can resolve them. Mirrors
        # what search_telegram does on collection.
        if any(isinstance(e, str) and re.match(r"^-?\d+$", e) for e in messages_with_media.keys()):
            try:
                self.dataset.update_status("Fetching dialog list to resolve numeric entity IDs")
                await client.get_dialogs(limit=None)
            except Exception as e:
                self.dataset.log(f"Could not pre-fetch dialogs for numeric ID resolution: {e}")

        # now actually download the media
        # todo: investigate if we can directly instantiate a MessageMediaPhoto instead of fetching messages
        media_done = 1
        for entity, message_ids in messages_with_media.items():
            # numeric entity IDs need to be wrapped as PeerChannel so Telethon
            # consults the session cache instead of trying to resolve them as
            # usernames/invite hashes via the API
            entity_for_telegram = SearchTelegram.parse_numeric_entity(entity)
            try:
                async for message in client.iter_messages(entity=entity_for_telegram, ids=message_ids):
                    if self.interrupted:
                        raise ProcessorInterruptedException(
                            f"Interrupted while downloading {self._media_label}s")

                    self.dataset.update_status(f"Downloading media {media_done:,}/{total_media:,}")
                    self.dataset.update_progress(media_done / total_media)

                    success = False
                    msg_id = f"{entity}-{message.id}" if message and hasattr(message, "id") else None
                    path = (self.staging_area.joinpath(self._get_filename(message, entity))
                            if msg_id and message.media is not None else None)
                    filename = path.name if path else f"{entity}-index-{media_done}"

                    if message is None:
                        reason_code = "message_unavailable"
                        reason_text = "Message no longer exists (it may have been deleted)"
                    elif message.media is None:
                        reason_code = "no_media"
                        reason_text = "Message has no media attached"
                    elif not self._can_download(message):
                        media_type_name = type(message.media).__name__
                        reason_code = "unsupported_media"
                        reason_text = (f"Media is {media_type_name}; Telegram did not deliver a "
                                       "downloadable file. If chat_noforwards=yes in the source "
                                       "dataset, this is expected.")
                    else:
                        try:
                            await self._download_to_path(client, message, path)
                            success = True
                            reason_code = "ok"
                            reason_text = "downloaded"
                        except (AttributeError, RuntimeError, ValueError, TypeError, BadRequestError) as e:
                            reason_code, reason_text = self.categorize_download_error(e)

                    self.reason_counts[reason_code] += 1
                    if not success:
                        msg_id_log = msg_id if msg_id else f"index {media_done:,}"
                        self.dataset.log(
                            f"Skipped {self._media_label} for message {msg_id_log} "
                            f"[{reason_code}]: {reason_text}")
                        self.flawless = False

                    self.metadata[filename] = {
                        "filename": filename,
                        "success": success,
                        "reason": reason_code,
                        "reason_description": reason_text,
                        "from_dataset": self.source_dataset.key,
                        "post_ids": [msg_id] if msg_id else []
                    }
                    media_done += 1

            except FloodError as e:
                later = "later"
                if hasattr(e, "seconds"):
                    later = f"in {timify(e.seconds)}"
                self.dataset.update_status(
                    f"Rate-limited by Telegram after downloading {media_done-1:,} "
                    f"{self._media_label}(s); halting download process. Try again {later}.",
                    is_final=True)
                self.flawless = False
                break

            except (ValueError, BadRequestError) as e:
                # entity-level failure: the whole channel could not be reached.
                # add to each message's metadata
                reason_code = "entity_unreachable"
                reason_text = (
                    f"Entity {entity} could not be reached: {e}. "
                    "If this is a numeric channel ID, the account may no longer be a member, "
                    "or the session may need to be re-warmed.")
                self.dataset.log(
                    f"Couldn't retrieve {self._media_label}s for entity {entity} "
                    f"[{reason_code}]: {reason_text}")
                self.flawless = False
                for mid in message_ids:
                    msg_id_full = f"{entity}-{mid}"
                    self.reason_counts[reason_code] += 1
                    self.metadata[msg_id_full] = {
                        "filename": "",
                        "success": False,
                        "reason": reason_code,
                        "reason_description": reason_text,
                        "from_dataset": self.source_dataset.key,
                        "post_ids": [msg_id_full]
                    }

        # end-of-run outcome breakdown into the dataset log so researchers can
        # see counts per category without parsing per-message lines
        if self.reason_counts:
            breakdown = ", ".join(f"{code}={count:,}"
                                  for code, count in self.reason_counts.most_common())
            self.dataset.log(f"Download outcome breakdown: {breakdown}")

        if client:
            await client.disconnect()

    @classmethod
    def map_metadata(cls, filename, data):
        """
        Iterator to yield modified metadata for CSV
        """
        row = {
            cls._metadata_count_label: len(data.get("post_ids", [])),
            "post_ids": ", ".join(map(str, data.get("post_ids", []))),
            "filename": filename,
            "download_successful": data.get('success', ""),
            "reason": data.get("reason", ""),
            "reason_description": data.get("reason_description", "")
        }

        yield row
