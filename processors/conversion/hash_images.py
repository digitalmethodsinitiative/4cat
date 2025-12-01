"""
Hash images
"""
import csv
import json

from PIL import UnidentifiedImageError

from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.helpers import UserInput, hash_image, stringify_hash
from processors.metrics.group_hashes import HashGrouper


__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class ImageHasher(BasicProcessor):
    """
    Hash images
    """
    type = "image-hasher"  # job type ID
    category = "Conversion"  # category
    title = "Hash images"  # title displayed in UI
    description = "Convert images to text hashes for comparison and similarity detection."  # description displayed in UI
    extension = "csv"

    references = [
        "[Imagehash library](https://github.com/JohannesBuchner/imagehash?tab=readme-ov-file)",
        "Explainer: [Perceptual hashing](https://www.hackerfactor.com/blog/index.php?/archives/432-Looks-Like-It.html)",
    ]

    # "phash": "Perceptual (DCT) hash: strong general-purpose near-duplicate. Robust to resize, JPEG, small blur/contrast tweaks; weaker to large crop/rotation. Hamming; size=16≈256-bit (use ~20–40 threshold), size=32≈1024-bit.",
    # "whash-haar": "Wavelet (Haar) hash: similar to pHash but often more stable to brightness/exposure shifts. Robust to resize/compression/exposure; weaker to large crop/rotation. Hamming; size=16≈256-bit.",
    # "whash-db4": "Wavelet (Daubechies-4) hash: more resistant to noise/compression and slight geometric changes than Haar; a bit slower. Hamming; size=16≈256-bit (use ~20–40 threshold).",
    # "crhash": "Crop-resistant perceptual hash: survives moderate crops, borders, overlays, and aspect changes; slowest. Returns multiple sub-hashes; compare with crop_resistant distance (not simple Hamming)."
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
            "hash-type-info": {
                    "type": UserInput.OPTION_INFO,
                    "help": "The following hash types are available: "
                            "**Perceptual (DCT) hash**: strong general-purpose near-duplicate. "
                            "**Wavelet (Daubechies-4) hash**: often more stable to brightness/exposure shifts; weaker to large crop/rotation. "
                            "**Crop-resistant perceptual hash**: survives moderate crops, borders, overlays, and aspect changes; slowest. Returns multiple sub-hashes (not simple Hamming).",
            },
            "hash-type": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Comparison method",
                "default": "phash",
                "options": {
                    "phash": "Perceptual (DCT)",
                    "whash-db4": "Wavelet (Daubechies-4)",
                    "crhash": "Crop-resistant perceptual"
                    }
            },
            "hash-size": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Hash size",
                "default": "16",
                "options": {
                    "16": "16 (fast, accurate)",
                    "32": "32 (slower, more accurate)"
                },
                "requires": "hash-type!=crhash"
            },
            "group-by": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Group similar images together",
                "default": False,
                "tooltip": "If enabled, images with similar hashes will be grouped together in the output. Single-link clustering (A similar to B, B similar to C => A, B, C in same group)."
            },
            "similarity-threshold": {
                "type": UserInput.OPTION_TEXT,
                "help": "Similarity threshold (percent)",
                "coerce_type": int,
                "default": 5,
                "min": 0,
                "max": 100,
                "requires": "group-by==true",
                "tooltip": "Maximum difference as a percentage of hash bits (0–100). Examples: ~4% ≈ 10/256 for size=16; ~4% ≈ 40/1024 for size=32. For crop-resistant, the % applies to each component hash."
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
        Loop through images and hashing them
        """
        hash_type = self.parameters.get("hash-type", "phash")
        # Fixed-length hashes use hash_size; crhash does not support
        if hash_type == "crhash":
            hash_size = None
        else:
            hash_size = int(self.parameters.get("hash-size", 16))
        group_by = self.parameters.get("group-by", False)
        similarity_pct = float(self.parameters.get("similarity-threshold", 4))

        # Get staging area
        staging_area = self.dataset.get_staging_area()

        # Extract metadata if present
        try:
            metadata_file = self.extract_archived_file_by_name(".metadata.json", self.source_file, staging_area)
        except FileNotFoundError:
            metadata_file = None

        metadata_extra_fields = ["post_ids", "post_id", "url", "from_dataset"]
        image_data_by_filename = {}
        if metadata_file:
            with open(metadata_file) as file:
                image_data = json.load(file)
                for url, item in image_data.items():
                    if "filename" in item:
                        image_data_by_filename[item["filename"]] = item
                    elif "files" in item:
                        files = item.get('files')
                        if not isinstance(files, list):
                            self.log.warning(f"Invalid 'files' entry in metadata (expected list, got {type(files)}); cannot use file metadata")
                            image_data_by_filename = {}
                            break
                        for file in files:
                            if "filename" in file:
                                # add extra fields from parent item if not present in file entry
                                for key in metadata_extra_fields:
                                    if key in file:
                                        continue
                                    elif key in item:
                                        file[key] = item[key]
                                image_data_by_filename[file["filename"]] = file
                                
                self.dataset.log("Found and loaded image metadata")
        else:
            self.dataset.log("No image metadata found")
            image_data_by_filename = {}

        # Set up CSV fieldnames (always include hash_size even if crhash to indicate 'None')
        base_fields = ["filename", "image_hash", "hash_type", "hash_size"]
        fieldnames = (["group"] if group_by else []) + base_fields
        if image_data_by_filename:
            example = next(iter(image_data_by_filename.values()))
            fieldnames.extend([key for key in metadata_extra_fields if key in example.keys()])

        processed = 0
        skipped = 0
        # Collect per-image info for optional grouping and CSV output
        items = []  # each item: {filename, hash_obj, hash_type, hash_size}
        self.dataset.update_status("Processing images and creating hashes")

        for image_file in self.iterate_archive_contents(self.source_file, staging_area=staging_area):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while hashing images")

            self.dataset.update_progress(processed / self.source_dataset.num_rows)
            if processed % 100 == 0:
                self.dataset.update_status(f"Processed {processed:,} of {self.source_dataset.num_rows:,} images")

            if image_file.name == ".metadata.json":
                continue
            try:
                image_hash = hash_image(image_file, hash_type, hash_size, as_string=False)
            except FileNotFoundError as e:
                skipped += 1
                self.dataset.log(f"Warning: Could not hash image {image_file.name}: {e}")
                continue
            except UnidentifiedImageError as e:
                skipped += 1
                self.dataset.log(f"Warning: Could not identify image {image_file.name}: {e}")
                continue
        
            processed += 1

            items.append({
                "filename": image_file.name,
                "hash_obj": image_hash,
                "hash_type": hash_type,
                "hash_size": hash_size,
            })

        if group_by:
            # Use HashGrouper to compute groups
            hashes = [it["hash_obj"] for it in items]
            group_labels = HashGrouper.compute_groups(hashes, hash_type, hash_size, similarity_pct)
            next_group_id = max(group_labels) + 1 if group_labels else 0
            for i, gid in enumerate(group_labels):
                items[i]["group"] = gid

        with self.dataset.get_results_path().open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for it in items:
                image_metadata = image_data_by_filename.get(it["filename"], {})
                
                # Convert hash object to string for CSV storage
                hash_str = stringify_hash(it["hash_obj"], it["hash_type"])
                row = {
                    **({"group": it.get("group", "")} if group_by else {}),
                    "filename": it["filename"],
                    "hash_size": it["hash_size"] if it["hash_size"] is not None else "None",
                    "image_hash": hash_str,
                    "hash_type": it["hash_type"],
                }
                # Add optional metadata fields if present
                for key in fieldnames:
                    if key not in row:
                        row[key] = image_metadata.get(key, "")
                writer.writerow(row)

        final_msg = f"Processed {processed:,} images"
        if group_by:
            final_msg += f", grouped into {next_group_id:,} groups (threshold={similarity_pct:.2f}%)"
        self.dataset.update_status(final_msg, is_final=True)
        self.dataset.finish(num_rows=processed)