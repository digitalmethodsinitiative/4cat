"""
Download non-video, non-photo file attachments from Telegram messages.

Picks up audio (voice notes, music), generic documents (PDFs, archives,
stickers), and image documents (images sent as files rather than photos).
Inherits the run loop, error categorization, and metadata structure from
`TelegramVideoDownloader`; only the type selection, file extension, and
admin/option surface change.
"""
import mimetypes
import re

from telethon import utils as telethon_utils

from common.lib.helpers import UserInput
from backend.lib.processor import ProcessorDescription
from processors.visualisation.download_telegram_videos import TelegramVideoDownloader
from common.lib.compatibility import Compatibility
from common.lib.outputs import MediaArchive

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class TelegramFileDownloader(TelegramVideoDownloader):
    """
    Telegram file downloader

    Companion to the video and image downloaders: handles the long tail of
    document attachments (audio, voice notes, PDFs, archives, stickers,
    image documents) that the other two skip. Output zip contains a mix of
    file types, so `media_type` is set to ``"file"`` -- followup processors
    that key off "video" or "image" will not pick this up.
    """
    type = "file-downloader-telegram"  # job type ID
    description = ProcessorDescription(
        title="Download Telegram files",
        category="Visual",
        tags=["download media", "external service"],
        description="Download the audio, documents, stickers, and other non-video, non-photo file attachments of Telegram messages and store them in a ZIP file.",
        info=[
            "A JSON metadata file recording the download outcome per message is included in the archive."
        ],
        warnings=[
            "Files are fetched through the Telegram API, so this can take a long time and some files may fail to download.",
            "Channels with 'Restrict Saving Content' enabled will refuse the download; those files cannot be retrieved.",
        ],
        icon="file",
    )
    extension = "zip"
    # a zip archive of media files
    output = MediaArchive(media="file")
    media_type = "file"

    # coarse map spec; is_compatible_with (below) is the runtime truth (Telegram API creds).
    # No preferred_followups -- file outputs are heterogeneous and don't map cleanly to
    # existing video/image follow-on processors.
    compatibility = Compatibility(types={"telegram-search"}, required_settings={"file-downloader-telegram.allow_files"})

    config = {
        "file-downloader-telegram.allow_files": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Allow file downloads",
            "tooltip": "Whether to download non-video, non-photo file attachments.",
        }
    }

    # ---- subclass hook overrides ----
    _media_label = "file"
    _metadata_count_label = "number_of_posts_with_file"
    # _file_extension default is unused here; _get_file_extension is per-message
    _file_extension = "bin"

    def _get_downloadable_types(self):
        types = []
        if self.parameters.get("include_audio"):
            types.append("audio")
        if self.parameters.get("include_documents"):
            types.append("application")
        if self.parameters.get("include_image_documents"):
            # image documents (sent as a file rather than as a photo) carry
            # mime image/* and so end up with attachment_type=="image" after
            # the search datasource splits the mime type
            types.append("image")
        return types

    def _can_download(self, message):
        # everything we accept here is a Document attachment
        return hasattr(message.media, "document")

    def _get_file_extension(self, message):
        """
        Pick an extension based on the document's filename attribute (if
        Telegram provided one) or its MIME type. Falls back to "bin" so we
        never produce an extensionless file.
        """
        # Telethon helpfully resolves this for us
        try:
            ext = telethon_utils.get_extension(message)
            if ext:
                return ext.lstrip(".") or "bin"
        except Exception:
            pass
        # fall back to mimetypes module
        if hasattr(message.media, "document"):
            mime = getattr(message.media.document, "mime_type", "") or ""
            guessed = mimetypes.guess_extension(mime)
            if guessed:
                return guessed.lstrip(".")
        return "bin"

    def _get_filename(self, message, entity):
        """
        Prefer the original filename Telegram delivered via
        ``DocumentAttributeFilename`` (exposed as ``message.file.name``).
        Falls back to the ``{entity}-{message_id}.{ext}`` default if no
        filename is present or sanitization wipes it out.

        Output is prefixed with ``{message_id}_`` to keep entries unique
        within the zip even if Telegram delivered the same filename across
        multiple messages, and to preserve traceability back to the source
        message.
        """
        original = None
        try:
            original = message.file.name
        except (AttributeError, ValueError):
            original = None

        if not original:
            return super()._get_filename(message, entity)

        # strip path separators and control characters; keep spaces and
        # other punctuation since researchers may want the original name
        sanitized = re.sub(r"[\\/\x00-\x1f]", "_", original).strip().strip(".")
        if not sanitized:
            return super()._get_filename(message, entity)

        return f"{message.id}_{sanitized}"

    # ---- option / compatibility overrides ----

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
        # Using same max config as video downloader as proxy (should allow infinite if desired).
        # 4CAT convention: admin sets the config to 0 to mean "unlimited". In that mode the
        # user can also enter 0 to actually fetch all items.
        max_files = int(config.get('video-downloader-telegram.max_videos', 100))
        options = {
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "help": "Amount of files" if max_files == 0 else f"Amount of files (max {max_files:,})",
                "default": 10 if max_files == 0 else min(10, max_files),
                "min": 0 if max_files == 0 else 1,
                "tooltip": "Maximum number of files to download" + (
                    " (set to 0 to download all files)" if max_files == 0 else "")
            },
            "include_audio": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Include audio",
                "default": True,
                "tooltip": "Voice notes, music files, and other audio attachments."
            },
            "include_documents": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Include documents",
                "default": True,
                "tooltip": "PDFs, archives, stickers, and other application/* attachments."
            },
            "include_image_documents": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Include image documents",
                "default": False,
                "tooltip": "Images sent as a file rather than as a photo. Most channel photos "
                           "are not in this category -- those are handled by the image downloader."
            },
        }
        if max_files != 0:
            options["amount"]["max"] = max_files
        return options

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        if not config.get("file-downloader-telegram.allow_files", False):
            return False
        return cls._is_telegram_dataset(module)
