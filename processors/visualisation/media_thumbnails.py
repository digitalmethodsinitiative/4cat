"""
Reduce every media file in a dataset to a thumbnail.
"""
import io
import shutil
import zipfile

from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from backend.lib.processor import BasicProcessor
from common.lib.archive_metadata import is_support_file
from common.lib.compatibility import Compatibility
from common.lib.exceptions import DataSetException, ProcessorInterruptedException
from common.lib.user_input import UserInput
from processors.machine_learning.embed_media import read_post_id_map

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

# Files a thumbnail is decoded from with ffmpeg rather than opened with Pillow
VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".mpg", ".mpeg"}

# Folder with thumbs
THUMBNAIL_FOLDER = "thumbnails"


class MediaThumbnails(BasicProcessor):
    """
    Turn a collection of images or videos into thumbnails.

    The archive holds nothing but the thumbnails and the metadata describing
    them, so that anything which consumes a media archive can consume this one.
    Packing them into a sprite sheet is a separate step, `media-sprite`.
    """
    type = "media-thumbnails"  # job type ID
    category = "Visual"  # category
    title = "Generate thumbnails"  # title displayed in UI
    description = ("Reduce every image or video frame to a small square thumbnail, each saved as its own file.")
    extension = "zip"  # extension of result file, used internally and in UI
    media_type = "image"  # media type of the dataset

    # also allow video, which is a bit odd perhaps, but sometimes you just want the thumbnails in post-processors
    # and don't want to also download images, which takes longer.
    compatibility = Compatibility(
        media_types={"image", "video"},
        type_prefixes={"image-downloader", "video-downloader"},
        preferred_followups=["media-sprite", "image-embeddings"],
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
        try:
            columns = parent_dataset.top_parent().get_columns() if parent_dataset else []
        except DataSetException:
            columns = []

        options = {
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

        if columns:
            options["min_column"] = {
                "type": UserInput.OPTION_CHOICE,
                "help": "Only for posts with",
                "options": {"": "No threshold (all files)", **{column: column for column in columns}},
                "default": "",
                "tooltip": "Only media from posts at or above the threshold get a thumbnail.",
            }
            options["min_value"] = {
                "type": UserInput.OPTION_TEXT,
                "help": "At least",
                "default": 0,
                "coerce_type": float,
                "requires": "min_column",
            }

        return options

    def process(self):
        """
        Make a thumbnail per file and write them all to one archive.
        """
        size = self.parameters.get("thumbnail_size", 48)
        limit = self.parameters.get("amount", 0)

        min_column = self.parameters.get("min_column", "")
        min_value = self.parameters.get("min_value", 0)
        allowed = self.get_files_above_threshold(min_column, min_value) if min_column else None
        if allowed is not None and not allowed:
            self.dataset.finish_with_error(f"No media files come from posts with '{min_column}' of at least "
                                           f"{min_value:g}, so there is nothing to show.")
            return

        available = len(allowed) if allowed is not None else self.source_dataset.num_rows
        max_processed = min(limit, available) if limit else available

        ffmpeg = shutil.which(self.config.get("video-downloader.ffmpeg_path"))
        ffprobe = shutil.which("ffprobe".join(ffmpeg.rsplit("ffmpeg", 1))) if ffmpeg else None

        staging_area = self.dataset.get_staging_area()

        source_metadata = self.get_media_metadata()
        metadata = self.dataset.new_media_metadata(
            processor_type=self.type,
            from_dataset=((source_metadata.from_dataset if source_metadata else None)
                          or self.source_dataset.key),
        )

        def provenance(source_name):
            """The post IDs and URL the media file with this name came from."""
            entry = source_metadata.get_entry(source_name) if source_metadata else None
            return (entry.get("post_ids", []) if entry else []), (entry.get("url") if entry else None)

        thumbnails = []
        processed = 0
        skipped = 0
        below_threshold = 0
        needed_ffmpeg = 0

        self.dataset.update_status("Extracting thumbnails")
        for item in self.source_dataset.iterate_items(self, staging_area=staging_area, immediately_delete=False):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while extracting thumbnails")

            if processed >= max_processed:
                break

            media_path = item.file if hasattr(item, "file") else None
            if not media_path:
                continue

            if allowed is not None and media_path.stem not in allowed:
                below_threshold += 1
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
                post_ids, url = provenance(media_path.name)
                metadata.add_failure(post_ids=post_ids, url=url, reason="ffmpeg_unavailable",
                                     reason_description="a video needs ffmpeg to take a frame from, and ffmpeg is "
                                                        "not available",
                                     extra={"source_filename": media_path.name})
                continue

            reason_description = "the file could not be read as an image or video"
            try:
                thumbnail = self.make_thumbnail(media_path, size, is_video, ffmpeg, ffprobe)
            except ProcessorInterruptedException:
                raise
            except Exception as e:
                self.dataset.log(f"Skipping {media_path.name}: {e}")
                thumbnail = None
                reason_description = str(e)

            if thumbnail is None:
                skipped += 1
                post_ids, url = provenance(media_path.name)
                metadata.add_failure(post_ids=post_ids, url=url, reason="thumbnail_failed",
                                     reason_description=reason_description,
                                     extra={"source_filename": media_path.name})
                continue

            thumbnails.append((media_path.name, thumbnail))

        if not thumbnails:
            self.dataset.finish_with_error("None of the media files could be read, so there is nothing to show.")
            return

        self.dataset.update_status(f"Writing {len(thumbnails):,} thumbnails")
        with zipfile.ZipFile(self.dataset.get_results_path(), "w", zipfile.ZIP_DEFLATED) as archive:
            files = {}
            for source_name, thumbnail in thumbnails:
                member = f"{THUMBNAIL_FOLDER}/{self.thumbnail_name(source_name, files)}"
                single = io.BytesIO()
                thumbnail.save(single, "JPEG", quality=80, optimize=True)
                archive.writestr(member, single.getvalue())
                files[source_name] = member

                # keyed by the path inside this archive, as the schema expects.
                # `source_filename` is what a sprite sheet made from this
                # archive keys its tiles by, so it has to be recorded here
                post_ids, url = provenance(source_name)
                metadata.add_item(member, post_ids=post_ids, url=url,
                                  extra={"source_filename": source_name})

            # written to the staging area first, so that it is validated and
            # fully on disk before it goes into the archive
            metadata_file = metadata.write(staging_area)
            archive.write(metadata_file, metadata_file.name)

        status = f"Extracted {len(thumbnails):,} thumbnails at {size}px"
        if below_threshold:
            status += f", left out {below_threshold:,} files from posts with '{min_column}' below {min_value:g}"
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

    def get_files_above_threshold(self, column: str, threshold: float) -> set:
        """
        Find the media files that come from at least one post whose value in
        `column` is at or above `threshold`.

        :param str column:  Column of the original dataset to compare
        :param float threshold:  Lowest value that still gets a thumbnail
        :return set:  Filenames without extension, only of files that are in
          the archive
        """
        archive_path = self.source_dataset.get_results_path()
        post_id_map = read_post_id_map(archive_path, log=self.dataset.log)
        if not post_id_map:
            self.dataset.log("The archive does not say which posts its files came from, so none can be shown")
            return set()

        wanted = {str(post_id) for post_ids in post_id_map.values() for post_id in post_ids}

        self.dataset.update_status(f"Reading '{column}' from the original dataset")
        passing = set()
        for item in self.source_dataset.top_parent().iterate_items(self):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while reading the original dataset")

            post_id = str(item.get("id"))
            if post_id not in wanted:
                continue

            try:
                if float(item.get(column)) >= threshold:
                    passing.add(post_id)
            except (TypeError, ValueError):
                pass

        # the metadata also lists files that failed to download; only count
        # what is actually there, so progress adds up
        with zipfile.ZipFile(archive_path) as archive:
            present = {Path(name).stem for name in archive.namelist() if not is_support_file(name)}

        return {stem for stem, post_ids in post_id_map.items()
                if stem in present and any(str(post_id) in passing for post_id in post_ids)}

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
