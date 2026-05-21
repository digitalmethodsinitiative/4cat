"""
Filter by unique images
"""
import shutil

from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException, MetadataException
from common.lib.helpers import UserInput, hash_file

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class UniqueImageFilter(BasicProcessor):
    """
    Retain only unique images, by a user-defined metric
    """
    type = "image-downloader-unique"  # job type ID
    category = "Visualisation"  # category
    title = "Filter for unique images"  # title displayed in UI
    description = "Only keeps one instance per image using various detection methods."  # description displayed in UI
    extension = "zip"

    references = [
        "[Imagehash library](https://github.com/JohannesBuchner/imagehash?tab=readme-ov-file)",
        "Explainer: [Average hash](https://www.hackerfactor.com/blog/index.php?/archives/432-Looks-Like-It.html)",
        "Explainer: [Perceptual hashing](https://www.hackerfactor.com/blog/index.php?/archives/432-Looks-Like-It.html)",
        "Explainer: [Difference hash](https://www.hackerfactor.com/blog/index.php?/archives/529-Kind-of-Like-That.html)",

    ]

    @classmethod
    def get_options(cls, parent_dataset=None, config=None) -> dict:
        """
        Get processor options

        :param parent_dataset DataSet:  An object representing the dataset that
            the processor would be or was run on. Can be used, in conjunction with
            config, to show some options only to privileged users.
        :param config ConfigManager|None config:  Configuration reader (context-aware)
        :return dict:   Options for this processor
        """
        return {
            "hash-type": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Comparison method",
                "default": "file-hash",
                "options": {
                    "file-hash": "File hash (files need to be byte-by-byte duplicates)",
                    "colorhash": "Colour hash (good at colours, worse at shapes)",
                    "phash": "Perceptual hash (decent at colours and shapes)",
                    "average_hash": "Average hash (good at crops, less tolerant of differences than perceptual hashing)",
                    "dhash": "Difference hash (similar to average hash, better at photos and art)"
                }
            }
        }

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Allow processor on image archives

        :param module: Module to determine compatibility with
        """
        return module.get_media_type() == "image" or module.type.startswith(
            "image-downloader") or module.type == "video-frames"

    def process(self):
        """
        Loop through images and only retain ones that have not been seen yet

        :return:
        """
        seen_hashes = set()
        hash_map = {}
        hash_type = self.parameters.get("hash-type")
        dupes = 0
        processed = 0
        staging_area = self.dataset.get_staging_area()

        self.dataset.update_status("Processing images and looking for duplicates")
        for image in self.source_dataset.iterate_items():
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while filtering for unique images")

            self.dataset.update_progress(processed / self.source_dataset.num_rows)
            if processed % 100 == 0:
                self.dataset.update_status(f"Processed {processed:,} of {self.source_dataset.num_rows:,} images, "
                                             f"found {dupes:,} duplicate(s)")
            processed += 1

            if image.file.name == ".metadata.json":
                continue

            image_hash = hash_file(image.file, hash_type)

            if image_hash not in seen_hashes:
                seen_hashes.add(image_hash)
                shutil.copy2(image.file, staging_area)
                hash_map[image_hash] = image.file.name
            else:
                self.dataset.log(f"{image.file.name} is a duplicate of {hash_map[image_hash]} - skipping")
                dupes += 1

        try:
            source_metadata = self.source_dataset.read_media_metadata()
        except (FileNotFoundError, MetadataException):
            source_metadata = None

        new_metadata = self.dataset.new_media_metadata(
            processor_type=self.type,
            from_dataset=(source_metadata.from_dataset if source_metadata else self.source_dataset.key),
        )
        inverse_hashmap = {v: k for k, v in hash_map.items()}
        if source_metadata is not None:
            for filename, item in source_metadata.iter_entries():
                if filename not in inverse_hashmap:
                    continue
                extra = dict(item.get("extra") or {})
                extra["hash"] = inverse_hashmap[filename]
                extra["hash_type"] = hash_type
                new_metadata.add_item(
                    filename,
                    post_ids=item.get("post_ids", []),
                    url=item.get("url"),
                    extra=extra,
                )
        else:
            for h, filename in hash_map.items():
                new_metadata.add_item(
                    filename, post_ids=[],
                    extra={"hash": h, "hash_type": hash_type},
                )

        new_metadata.write(staging_area)

        self.dataset.update_status(f"Image archive filtered, found {dupes:,} duplicate(s)", is_final=True)
        self.write_archive_and_finish(staging_area, len(hash_map), finish=True)
