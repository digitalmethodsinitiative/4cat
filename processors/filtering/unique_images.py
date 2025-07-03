"""
Filter by unique images
"""
import shutil
import json

from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException
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
    description = "Only keeps one instance per image, using a choice of detection method."  # description displayed in UI
    extension = "zip"

    references = [
        "[Imagehash library](https://github.com/JohannesBuchner/imagehash?tab=readme-ov-file)",
        "Explainer: [Average hash](https://www.hackerfactor.com/blog/index.php?/archives/432-Looks-Like-It.html)",
        "Explainer: [Perceptual hashing](https://www.hackerfactor.com/blog/index.php?/archives/432-Looks-Like-It.html)",
        "Explainer: [Difference hash](https://www.hackerfactor.com/blog/index.php?/archives/529-Kind-of-Like-That.html)",

    ]

    options = {
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
        metadata = None
        dupes = 0
        processed = 0
        staging_area = self.dataset.get_staging_area()

        self.dataset.update_status("Processing images and looking for duplicates")
        for image_file in self.iterate_archive_contents(self.source_file):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while filtering for unique images")

            self.dataset.update_progress(processed / self.source_dataset.num_rows)
            if processed % 100 == 0:
                self.dataset.update_status(f"Processed {processed:,} of {self.source_dataset.num_rows:,} images, "
                                             f"found {dupes:,} duplicate(s)")
            processed += 1

            if image_file.name == ".metadata.json":
                with image_file.open() as infile:
                    metadata = json.load(infile)
                continue

            image_hash = hash_file(image_file, self.parameters.get("hash-type"))

            if image_hash not in seen_hashes:
                seen_hashes.add(image_hash)
                shutil.copy2(image_file, staging_area)
                hash_map[image_hash] = image_file.name
            else:
                self.dataset.log(f"{image_file.name} is a duplicate of {hash_map[image_hash]} - skipping")
                dupes += 1

        new_metadata = {}
        inverse_hashmap = {v: k for k, v in hash_map.items()}
        if metadata:
            for url, item in metadata.items():
                if item["filename"] in inverse_hashmap:
                    new_metadata[inverse_hashmap[item["filename"]]] = {
                        **item,
                        "hash": inverse_hashmap[item["filename"]],
                        "hash_type": self.parameters.get("hash-type")
                    }
        else:
            new_metadata = {hash_map[k]: {"filename": hash_map[k], "hash": k, "hash_type": self.parameters.get("hash-type")} for k in hash_map}

        with staging_area.joinpath(".metadata.json").open("w") as outfile:
            json.dump(new_metadata, outfile)

        self.dataset.update_status(f"Image archive filtered, found {dupes:,} duplicate(s)", is_final=True)
        self.write_archive_and_finish(staging_area, len(hash_map), finish=True)
