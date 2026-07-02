"""
Download images from Telegram message attachments

A thin specialization of `download_telegram_videos.TelegramVideoDownloader`:
swaps the downloadable types, file extension, and adds a thumbnail fallback
for video documents and webpage previews.
"""
from common.lib.helpers import UserInput
from backend.lib.processor import ProcessorDescription
from processors.visualisation.download_images import ImageDownloader
from processors.visualisation.download_telegram_videos import TelegramVideoDownloader
from common.lib.compatibility import Compatibility
from common.lib.outputs import MediaArchive

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class TelegramImageDownloader(TelegramVideoDownloader):
    """
    Telegram image downloader

    Downloads attached images from Telegram messages and saves as zip archive.
    Inherits the run loop, error categorization, and metadata structure from
    `TelegramVideoDownloader`; only the media-specific bits are overridden.
    """
    type = "image-downloader-telegram"  # job type ID
    description = ProcessorDescription(
        title="Download Telegram images",
        category="Visual",
        tags=["download media", "external service"],
        description="Download the images attached to Telegram messages and store them in a ZIP file. Video and link preview thumbnails can optionally be included. A JSON metadata file recording the download outcome per message is included in the archive.",
        warnings=[
            "Images are fetched through the Telegram API, so this can take a long time and some images may fail to download.",
            "Channels with 'Restrict Saving Content' enabled will refuse the download; those images cannot be retrieved.",
        ],
        icon="images",
    )
    extension = "zip"
    # a zip archive of media files
    output = MediaArchive(media="image")
    media_type = "image"

    # coarse map spec; is_compatible_with (below) is the runtime truth (Telegram API creds)
    compatibility = Compatibility(types={"telegram-search"}, preferred_followups=ImageDownloader.followups)

    config = {
        "image-downloader-telegram.max": {
            'type': UserInput.OPTION_TEXT,
            'default': "1000",
            'help': 'Max images',
            'tooltip': "Maxmimum number of Telegram images a user can download.",
        },
    }

    # ---- subclass hook overrides ----
    _file_extension = "jpeg"
    _media_label = "image"
    _metadata_count_label = "number_of_posts_with_image"

    def _get_downloadable_types(self):
        types = ["photo"]
        if self.parameters.get("video-thumbnails"):
            types.append("video")
        if self.parameters.get("website-thumbnails"):
            types.append("url")
        return types

    def _can_download(self, message):
        # we can fetch photos directly, and pull a thumbnail off documents
        # (used for video thumbnails) and webpage previews
        return hasattr(message.media, "photo") or hasattr(message.media, "document")

    async def _download_to_path(self, client, message, path):
        if hasattr(message.media, "photo"):
            await message.download_media(str(path))
        else:
            # video / webpage thumbnail
            await client.download_media(message, str(path), thumb=-1)

    # ---- option / compatibility overrides ----

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
        max_number_images = int(config.get('image-downloader-telegram.max', 1000))

        options = {
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "help": "No. of images" if max_number_images == 0 else f"No. of images (max {max_number_images})",
                "default": 100,
                "min": 0 if max_number_images == 0 else 1,
                "tooltip": f"Maximum number of images to download{' (set to 0 to download all images)' if max_number_images == 0 else ''}"
            },
            "video-thumbnails": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Include videos (as thumbnails)",
                "default": False
            },
            "website-thumbnails": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Include link thumbnails",
                "default": False,
                "tooltip": "This includes e.g. thumbnails for linked YouTube videos"
            }
        }

        if max_number_images != 0:
            options["amount"]["max"] = max_number_images

        return options

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        # image downloads are not gated behind the allow_videos admin toggle
        return cls._is_telegram_dataset(module)
