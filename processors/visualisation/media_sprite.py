"""
Merge a dataset of thumbnails into one sprite sheet.
"""
import base64
import io
import json
import math
import zipfile

from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from backend.lib.processor import BasicProcessor
from common.lib.compatibility import Compatibility
from common.lib.exceptions import DataSetException, ProcessorInterruptedException
from common.lib.user_input import UserInput

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

SPRITE_NAME = "sprite.jpg"

class MediaSprite(BasicProcessor):
    """
    Merge a dataset of thumbnails into a single sprite sheet.
    """
    type = "media-sprite"  # job type ID
    category = "Visual"  # category
    title = "Generate sprite sheet"  # title displayed in UI
    description = ("Merge thumbnails into a single image (sprite sheet), together with a metadata file that "
                   "indicates the position of each image. Can be used by some other processors to display thumbnails.")
    extension = "zip"  # extension of result file, used internally and in UI
    # no media_type since the sheet is not really something to use in post-processors

    compatibility = Compatibility(
        types=["media-thumbnails"],
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
            "tile_size": {
                "type": UserInput.OPTION_TEXT,
                "help": "Tile size in pixels",
                "default": 48,
                "min": 16,
                "max": 256,
                "coerce_type": int,
                "tooltip": "Tiles are square and cropped from the middle.",
            },
            "quality": {
                "type": UserInput.OPTION_TEXT,
                "help": "Image quality",
                "default": 70,
                "min": 10,
                "max": 95,
                "coerce_type": int,
                "tooltip": "JPEG quality of the sheet.",
            },
        }

    def process(self):
        """
        Lay every thumbnail out in a square grid and write the sheet.
        """
        source_metadata = self.get_media_metadata()
        sources = self.source_filenames(source_metadata)

        self.dataset.update_status("Reading thumbnails")
        tiles = []
        unreadable = 0
        staging_area = self.dataset.get_staging_area()

        for item in self.source_dataset.iterate_items(self, staging_area=staging_area, immediately_delete=False):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while reading thumbnails")

            path = item.file if hasattr(item, "file") else None
            if not path:
                continue

            member = self.member_name(path, staging_area)
            try:
                with Image.open(path) as image:
                    thumbnail = image.convert("RGB")
            except (UnidentifiedImageError, OSError) as e:
                self.dataset.log(f"Skipping {path.name}: {e}")
                unreadable += 1
                continue

            tiles.append((sources.get(member, member), member, thumbnail))

        if not tiles:
            self.dataset.finish_with_error("None of the pictures could be read, so there is no sheet to make.")
            return

        # the smallest image determines the file overall thumbnail size
        requested = self.parameters.get("tile_size", 48)
        smallest = min(min(thumbnail.size) for _, _, thumbnail in tiles)
        size = min(requested, smallest)
        if size != requested:
            self.dataset.log(f"Using {size}px tiles rather than {requested}px: the smallest picture is {smallest}px")

        # square-ish
        columns = math.ceil(math.sqrt(len(tiles)))
        rows = math.ceil(len(tiles) / columns)

        self.dataset.update_status(f"Merging {len(tiles):,} pictures into a {columns}x{rows} sheet")
        sheet = Image.new("RGB", (columns * size, rows * size), (255, 255, 255))
        index, files = {}, {}
        collisions, position = 0, 0
        for source_name, member, thumbnail in tiles:
            if source_name in index:
                collisions += 1
                continue

            if thumbnail.size != (size, size):
                thumbnail = ImageOps.fit(thumbnail, (size, size), method=Image.LANCZOS)
            sheet.paste(thumbnail, ((position % columns) * size, (position // columns) * size))
            index[source_name] = position
            files[source_name] = member
            position += 1

        buffer = io.BytesIO()
        sheet.save(buffer, "JPEG", quality=self.parameters.get("quality", 70), optimize=True)

        # put layout info in .metadata.json
        metadata = self.dataset.new_media_metadata(
            processor_type=self.type,
            from_dataset=((source_metadata.from_dataset if source_metadata else None)
                          or self.source_dataset.key),
        )

        metadata.add_item(SPRITE_NAME, post_ids=[], extra={
            "tile_size": size,
            "columns": columns,
            "rows": rows,
            "count": len(index),
            "tiles": index,
            "files": files,
            # which dataset's filenames the tiles are keyed by, so a plot can
            # link a tile to the file it shows without knowing how the sheet
            # was made
            "tiles_in_dataset": self.keyed_dataset_key(bool(sources)),
        })

        with zipfile.ZipFile(self.dataset.get_results_path(), "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(SPRITE_NAME, buffer.getvalue())
            metadata_file = metadata.write(staging_area)
            archive.write(metadata_file, metadata_file.name)

        status = f"Merged {len(index):,} pictures of {size}px into a {columns}x{rows} sprite sheet"
        if unreadable:
            status += f", skipped {unreadable:,} unreadable files"
        if collisions:
            self.dataset.update_status(status, is_final=True)
            self.dataset.finish_with_warning(
                len(index), f"{status}. {collisions:,} pictures had duplicate names and were left out.")
            return

        self.dataset.update_status(status, is_final=True)
        self.dataset.finish(len(index))

    def keyed_dataset_key(self, renamed: bool) -> str | None:
        """
        The dataset whose filenames the tiles are keyed by.

        A thumbnail archive records which media file each thumbnail came from,
        so a sheet of thumbnails is keyed by names from the archive *above* it.
        Frames carry no such record and are keyed by their own names, so those
        name files in the dataset packed here.

        :param bool renamed:  Whether the source recorded original filenames
        :return str|None:  Dataset key, or `None` if the chain is broken
        """
        try:
            if not renamed:
                return self.source_dataset.key

            parent = self.source_dataset.get_parent()
            return parent.key if parent else None
        except DataSetException:
            return None

    @classmethod
    def find_for(cls, dataset) -> dict:
        """
        Return sprite datasets for a given dataset.

        Lives here rather than in the plots that draw sheets, so that there is
        one place that knows where a sheet sits, however it was made.

        :param dataset:  The dataset a plot would run on
        :return dict:  `{sheet key: label}`, empty when there are none
        """
        try:
            # the core walk, rather than one of our own: nearest first, and
            # without this dataset itself
            ancestors = list(reversed(dataset.get_genealogy()))[1:] if dataset else []
        except DataSetException:
            return {}

        for ancestor in ancestors:
            sheets = {}
            for source in ancestor.get_children():

                for sheet in source.get_children():
                    if sheet.type != cls.type or not sheet.is_finished():
                        continue

                    size = sheet.parameters.get("tile_size") or source.parameters.get("thumbnail_size", "?")
                    sheets[sheet.key] = f"{size}px, {sheet.num_rows:,} tiles"

            if sheets:
                return sheets

        return {}

    @staticmethod
    def source_filenames(source_metadata) -> dict:
        """
        Map each thumbnail to the media file it was made from.

        :param source_metadata:  Metadata of the source archive, or `None`
        :return dict:  `{member path in the archive: source filename}`
        """
        if not source_metadata:
            return {}

        return {member: entry["extra"]["source_filename"]
                for member, entry in source_metadata.iter_entries()
                if (entry.get("extra") or {}).get("source_filename")}

    @staticmethod
    def member_name(path: Path, staging_area: Path) -> str:
        """
        The path a staged file has inside the archive it came from.

        :param Path path:  Where the file was extracted to
        :param Path staging_area:  Root it was extracted into
        :return str:  Path inside the archive, with forward slashes
        """
        try:
            return path.relative_to(staging_area).as_posix()
        except ValueError:
            return path.name

    @staticmethod
    def read_sprite(dataset) -> dict | None:
        """
        Read a sprite sheet written by this processor.

        Lives here rather than in the processors that draw the sheet, so that
        the layout is written and read in one place.

        :param DataSet dataset:  A finished `media-sprite` dataset
        :return dict|None:  `{uri, tile, cols, tiles, files}` where `tiles` maps
          a source filename to its tile index and `files` to the individual
          thumbnail inside the *thumbnail* archive, or `None` if the archive is
          unusable.
        """
        path = dataset.get_results_path()
        if not path.exists() or not zipfile.is_zipfile(path):
            return None

        try:
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                if SPRITE_NAME not in names or ".metadata.json" not in names:
                    return None

                layout = json.loads(archive.read(".metadata.json"))
                sprite = archive.read(SPRITE_NAME)
        except (zipfile.BadZipFile, json.JSONDecodeError, KeyError, OSError):
            return None

        # read straight out of the file rather than through the metadata class:
        # this is called from a processor that only wants the layout, and an
        # unreadable sheet should come back as None rather than raise
        entry = (layout.get("items") or {}).get(SPRITE_NAME) or {}
        extra = entry.get("extra") or {}
        if not extra.get("tiles"):
            return None

        return {
            "uri": "data:image/jpeg;base64," + base64.b64encode(sprite).decode("utf-8"),
            "tile": extra.get("tile_size"),
            "cols": extra.get("columns"),
            "tiles": extra.get("tiles") or {},
            "files": extra.get("files") or {},
            # the dataset the tile names belong to, for linking a tile to the
            # file it shows; absent in sheets made before this was recorded
            "linked": extra.get("tiles_in_dataset"),
        }
