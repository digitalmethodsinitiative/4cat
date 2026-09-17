"""
Generate an embedding per image via a multimodal embedding model.
"""
from PIL import Image, ImageOps, UnidentifiedImageError

from common.lib.compatibility import Compatibility
from common.lib.user_input import UserInput
from processors.machine_learning.embed_media import EmbedMedia

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


class EmbedImages(EmbedMedia):
    """
    Send each image to a multimodal embedding model and store the vector it
    returns, so images can be compared, mapped and searched by content.
    """
    type = "image-embeddings"  # job type ID
    category = "Visual"  # category
    title = "Generate image embeddings"  # title displayed in UI
    description = ("Generate a numerical representation (an 'embedding') of each image using a multimodal embedding "
                   "model. This allows images to be compared and clustered. Images are compressed before sending. "
                   "Requires an embedding model that accepts images, such as Qwen3-VL-Embedding.")
    extension = "ndjson"  # extension of result file, used internally and in UI

    media_label = "image"
    media_label_plural = "images"
    model_requirement_note = "not only text"
    working_filename = "compressed.jpg"
    annotation_label = "image embedding"

    compatibility = Compatibility(
        media_types={"image"},
        type_prefixes={"image-downloader"},
        preferred_followups=["embedding-map", "embedding-similarity"],
    )

    @classmethod
    def get_media_options(cls, config=None) -> dict:
        """
        Options controlling how an image is made smaller before it is sent.

        :param ConfigManager|None config:  Configuration reader (context-aware)
        :return dict:  Options for this processor
        """
        return {
            "compression_info": {
                "type": UserInput.OPTION_INFO,
                "help": "Compression speeds up requests. Reducing the size helps the most, and most models scale "
                        "images down to a few hundred pixels anyway. Very large images can also exceed the model's "
                        "context window and be rejected.",
            },
            "max_size": {
                "type": UserInput.OPTION_TEXT,
                "help": "Max width/height in pixels",
                "default": 448,
                "min": 64,
                "max": 1920,
                "coerce_type": int,
                "tooltip": "Images larger than this are scaled down, keeping their aspect ratio.",
            },
            "quality": {
                "type": UserInput.OPTION_TEXT,
                "help": "Compression level",
                "default": 85,
                "min": 1,
                "max": 95,
                "coerce_type": int,
                "tooltip": "Min: 1, max: 95. JPEG quality: lower means smaller files and lower quality. 85 is a "
                           "reasonable trade-off, below 50 makes the image grainy.",
            },
        }

    def skip_reason(self, media_path) -> str | None:
        """
        Leave out files Pillow cannot open as a bitmap.

        SVGs are vector files and are common in image archives, so they are
        named explicitly rather than reported as a generic failure.

        :param Path media_path:  File that would be embedded
        :return str|None:  Why the file is skipped, or `None` to embed it.
        """
        if media_path.suffix.lower() == ".svg":
            return "SVG files cannot be embedded"

        return None

    def prepare_media(self, media_path, output_path) -> tuple:
        """
        Re-encode an image smaller and return it as a base64 media descriptor.

        Pixel size matters most: models scale images to a fixed resolution
        anyway, so anything larger is bytes spent on nothing. Everything is
        written out as JPEG - the model reads a bitmap, so a PNG's lossless
        compression only costs transfer size.

        :param Path media_path:  Image to prepare
        :param Path output_path:  Where to write the re-encoded image
        :return tuple:  `(media descriptor, original size, sent size)`
        """
        output_path.unlink(missing_ok=True)
        max_size = self.parameters.get("max_size", 448)

        try:
            with Image.open(media_path) as image:
                # lets the JPEG decoder skip straight to roughly the size we
                # want instead of decoding at full resolution first
                image.draft("RGB", (max_size, max_size))

                # photos carry their rotation in EXIF rather than in the pixels;
                # without this a sideways photo is embedded sideways
                image = ImageOps.exif_transpose(image)

                # JPEG has no alpha channel, and paletted or 16-bit images need
                # converting before they can be saved as one
                if image.mode != "RGB":
                    image = image.convert("RGB")

                image.thumbnail((max_size, max_size), Image.LANCZOS)
                image.save(output_path, "JPEG", quality=self.parameters.get("quality", 85), optimize=True)
        except (UnidentifiedImageError, OSError, ValueError) as e:
            raise RuntimeError(f"could not read image: {e}")

        original_size = media_path.stat().st_size
        sent_size = output_path.stat().st_size
        self.dataset.log(f"{media_path.name}: {original_size / 1024:.0f} KB -> {sent_size / 1024:.0f} KB")

        payload = {"type": "image", "mime": "image/jpeg", "data": self.encode(output_path)}
        output_path.unlink(missing_ok=True)

        return payload, original_size, sent_size
