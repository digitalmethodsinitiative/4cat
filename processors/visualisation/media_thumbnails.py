"""
Reduce every media file in a dataset to a thumbnail. Also make a sprite sheet.
"""
import base64
import io
import json
import math
import shutil
import zipfile

from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from backend.lib.processor import BasicProcessor
from common.lib.compatibility import Compatibility
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.user_input import UserInput

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

# Files a thumbnail is decoded from with ffmpeg rather than opened with Pillow
VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".mpg", ".mpeg"}

# Name of sprite and lookup files
SPRITE_NAME = "sprite.jpg"
INDEX_NAME = "index.json"

# Folder with thumbs
THUMBNAIL_FOLDER = "thumbnails"


class MediaThumbnails(BasicProcessor):
    """
    Turn a collection of images or videos into thumbnails and a sprite sheet of thumbnails.
    """
    type = "media-thumbnails"  # job type ID
    category = "Visual"  # category
    title = "Extract thumbnails"  # title displayed in UI
    description = ("Reduce every image or frame from a video to a small square thumbnail. Thumbnails are saved "
                   "as separate files as well as a single image (a sprite sheet).")
    extension = "zip"  # extension of result file, used internally and in UI

    compatibility = Compatibility(
        media_types={"image", "video"},
        type_prefixes={"image-downloader", "video-downloader"},
    )

    @classmethod
    def get_options(cls, parent_dataset=None, config=None) -> dict:
        """
        Get processor options

        :param parent_dataset DataSet:  An object representing the dataset that
            the processor would be or was run on.
        :param config ConfigManager|None config:  Configuration reader (context-aware)
        :return dict:   Options for this processor
        """
        return {
            "thumbnail_size": {
                "type": UserInput.OPTION_TEXT,
                "help": "Thumbnail size in pixels",
                "default": 48,
                "min": 16,
                "max": 256,
                "coerce_type": int,
                "tooltip": "Thumbnails are square and cropped from the middle."
            },
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "help": "No. of files",
                "default": 0,
                "min": 0,
                "coerce_type": int,
                "tooltip": "Use '0' for all files. Video extraction is slow.",
            },
        }

    def process(self):
        """
        Make a thumbnail per file and write to sprite sheet.
        """
        size = self.parameters.get("thumbnail_size", 48)
        limit = self.parameters.get("amount", 0)
        max_processed = min(limit, self.source_dataset.num_rows) if limit else self.source_dataset.num_rows

        ffmpeg = shutil.which(self.config.get("video-downloader.ffmpeg_path"))
        ffprobe = shutil.which("ffprobe".join(ffmpeg.rsplit("ffmpeg", 1))) if ffmpeg else None

        staging_area = self.dataset.get_staging_area()
        thumbnails = []
        index = {}
        processed = 0
        skipped = 0
        needed_ffmpeg = 0

        self.dataset.update_status("Extracting thumbnails")
        for item in self.source_dataset.iterate_items(self, staging_area=staging_area, immediately_delete=False):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while extracting thumbnails")

            if processed >= max_processed:
                break

            media_path = item.file if hasattr(item, "file") else None
            if not media_path or media_path.name == ".metadata.json":
                # the archive carries its metadata alongside the media files
                continue

            processed += 1
            if processed % 25 == 0 or processed == 1:
                self.dataset.update_status(f"Extracting thumbnail {processed:,}/{max_processed:,} "
                                           f"({media_path.name})")
                self.dataset.update_progress(processed / max_processed)

            is_video = media_path.suffix.lower() in VIDEO_SUFFIXES
            if is_video and not ffmpeg:
                needed_ffmpeg += 1
                skipped += 1
                continue

            try:
                thumbnail = self.make_thumbnail(media_path, size, is_video, ffmpeg, ffprobe)
            except ProcessorInterruptedException:
                raise
            except Exception as e:
                self.dataset.log(f"Skipping {media_path.name}: {e}")
                thumbnail = None

            if thumbnail is None:
                skipped += 1
                continue

            index[media_path.name] = len(thumbnails)
            thumbnails.append((media_path.name, thumbnail))

        if not thumbnails:
            self.dataset.finish_with_error("None of the media files could be read, so there is nothing to show.")
            return

        self.dataset.update_status(f"Merging {len(thumbnails):,} thumbnails into a sprite sheet")
        columns = math.ceil(math.sqrt(len(thumbnails)))
        rows = math.ceil(len(thumbnails) / columns)
        sheet = Image.new("RGB", (columns * size, rows * size), (255, 255, 255))
        for position, (_, thumbnail) in enumerate(thumbnails):
            sheet.paste(thumbnail, ((position % columns) * size, (position // columns) * size))

        buffer = io.BytesIO()
        sheet.save(buffer, "JPEG", quality=70, optimize=True)

        # one archive holding the sheet and the lookup: keyed by filename rather
        # than position, so a processor that reads this can filter or reorder its
        # own items without the tiles going out of step
        with zipfile.ZipFile(self.dataset.get_results_path(), "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(SPRITE_NAME, buffer.getvalue())

            # each thumbnail on its own as well: a sprite sheet is only useful to
            # something that can blit tiles, while a plain file is useful to
            # anything
            files = {}
            for source_name, thumbnail in thumbnails:
                member = f"{THUMBNAIL_FOLDER}/{self.thumbnail_name(source_name, files)}"
                single = io.BytesIO()
                thumbnail.save(single, "JPEG", quality=80, optimize=True)
                archive.writestr(member, single.getvalue())
                files[source_name] = member

            archive.writestr(INDEX_NAME, json.dumps({
                "tile_size": size,
                "columns": columns,
                "rows": rows,
                "count": len(thumbnails),
                "tiles": index,
                "files": files,
            }))

        status = f"Extracted {len(thumbnails):,} thumbnails at {size}px into a {columns}x{rows} sprite sheet"
        if needed_ffmpeg:
            self.dataset.finish_with_warning(
                len(thumbnails), f"{status}. {needed_ffmpeg:,} videos were skipped because ffmpeg is not available.")
            return

        if skipped:
            status += f", skipped {skipped:,} unreadable files"

        self.dataset.update_status(status, is_final=True)
        self.dataset.finish(len(thumbnails))

    @staticmethod
    def thumbnail_name(source_name: str, taken: dict) -> str:
        """
        Name a thumbnail after the file it came from. Takes into account overlapping file names with different
        media types.

        :param str source_name:  Filename of the media the thumbnail is of
        :param dict taken:  Names already used, as `{source name: member path}`
        :return str:  Filename to store the thumbnail under
        """
        stem = Path(source_name).stem
        used = {member.rsplit("/", 1)[-1] for member in taken.values()}

        candidate = f"{stem}.jpg"
        suffix = 2
        while candidate in used:
            candidate = f"{stem}-{suffix}.jpg"
            suffix += 1

        return candidate

    def make_thumbnail(self, path, size: int, is_video: bool, ffmpeg, ffprobe):
        """
        Make one square thumbnail, decoding a video frame first if needed.

        :param Path path:  File to make a thumbnail of
        :param int size:  Width and height of the tile
        :param bool is_video:  Whether a frame has to be decoded first
        :param ffmpeg:  Path to ffmpeg, or None
        :param ffprobe:  Path to ffprobe, or None
        :return Image|None:  The thumbnail, or `None` if it could not be made.
        """
        source = path
        if is_video:
            source = self.extract_frame(path, ffmpeg, ffprobe)
            if source is None:
                return None

        try:
            with Image.open(source) as image:
                image.draft("RGB", (size * 2, size * 2))
                image = ImageOps.exif_transpose(image)
                if image.mode != "RGB":
                    image = image.convert("RGB")

                return ImageOps.fit(image, (size, size), method=Image.LANCZOS)
        except (UnidentifiedImageError, OSError, ValueError) as e:
            raise RuntimeError(f"could not read image ({e})")
        finally:
            if source is not path:
                source.unlink(missing_ok=True)

    def extract_frame(self, video_path, ffmpeg, ffprobe):
        """
        Grab a still from a tenth of the way into a video.

        :param Path video_path:  Video to take a frame from
        :param ffmpeg:  Path to ffmpeg
        :param ffprobe:  Path to ffprobe, or None to start from the beginning
        :return Path|None:  The written frame, or `None` on failure.
        """
        frame_path = Path(str(video_path) + ".frame.jpg")
        frame_path.unlink(missing_ok=True)

        offset = 0.0
        if ffprobe:
            probe = self.run_interruptable_process([
                ffprobe, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(video_path),
            ])
            try:
                offset = float(probe.stdout.decode("utf-8", errors="replace").strip()) * 0.1
            except (ValueError, AttributeError):
                # an unreadable duration is not worth failing over; start at 0
                offset = 0.0

        # -ss before -i seeks without decoding everything up to that point
        result = self.run_interruptable_process([
            ffmpeg, "-y", "-ss", f"{offset:.3f}", "-i", str(video_path),
            "-frames:v", "1", "-q:v", "3", str(frame_path),
        ], cleanup_paths=(frame_path,))

        if result.returncode != 0 or not frame_path.exists():
            frame_path.unlink(missing_ok=True)
            return None

        return frame_path

    @staticmethod
    def read_sprite(dataset) -> dict | None:
        """
        Read a sprite sheet written by this processor.

        Lives here rather than in the processors that use the thumbnail sprites to keep things central (e.g., embedding
        map).

        :param DataSet dataset:  A finished `media-thumbnails` dataset
        :return dict|None:  `{uri, tile, cols, tiles, files}` where `tiles` maps
          a source filename to its tile index and `files` to the individual
          thumbnail inside this archive, or `None` if the archive is unusable.
        """
        path = dataset.get_results_path()
        if not path.exists() or not zipfile.is_zipfile(path):
            return None

        try:
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                if SPRITE_NAME not in names or INDEX_NAME not in names:
                    return None

                index = json.loads(archive.read(INDEX_NAME))
                sprite = archive.read(SPRITE_NAME)
        except (zipfile.BadZipFile, json.JSONDecodeError, KeyError, OSError):
            return None

        return {
            "uri": "data:image/jpeg;base64," + base64.b64encode(sprite).decode("utf-8"),
            "tile": index.get("tile_size"),
            "cols": index.get("columns"),
            "tiles": index.get("tiles", {}),
            "files": index.get("files", {}),
        }
