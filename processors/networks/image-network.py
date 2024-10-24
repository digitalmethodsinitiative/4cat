"""
Make a bipartite Image-Item network
"""
import json

from backend.lib.processor import BasicProcessor
from common.lib.helpers import hash_file

import networkx as nx

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

from common.lib.exceptions import ProcessorInterruptedException
from common.lib.user_input import UserInput


class ImageGrapher(BasicProcessor):
    """
    Image network

    Creates a bipartite network of images and some attribute of the dataset the
    images were sourced from
    """
    type = "image-bipartite-network"  # job type ID
    category = "Networks"
    title = "Bipartite image-item network"  # title displayed in UI
    description = ("Create a GEXF network file with a bipartite network of "
                   "images and some data field (e.g. author) of the dataset "
                   "the images were sourced from. Suitable for use with Gephi's "
                   "'Image Preview' plugin.")
    extension = "gexf"  # extension of result file, used internally and in UI

    options = {}

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        root_dataset = None
        columns = None
        if parent_dataset:
            for parent in reversed(parent_dataset.get_genealogy()):
                if parent.get_columns():
                    root_dataset = parent
                    break
            columns = root_dataset.get_columns()

        return {
            "column": {
                "help": "Dataset field",
                "type": UserInput.OPTION_TEXT,
                "default": "id"
            },
            "image-value": {
                "help": "Image node label",
                "type": UserInput.OPTION_CHOICE,
                "options": {
                    "filename": "Image file name",
                    "url": "Image URL"
                },
                "tooltip": "The image node label will have this value. Depending on the network visualisation software "
                           "you use, one or the other is required to display the images as nodes."
            },
            "deduplicate": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Merge images",
                "tooltip": "Similar images can be merged into a single node, represented by the first image of the set "
                           "that was encountered.",
                "options": {
                    "none": "Do not merge",
                    "file-hash": "File hash (files need to be byte-by-byte duplicates)",
                    "colorhash": "Colour hash (good at colours, worse at shapes)",
                    "phash": "Perceptual hash (decent at colours and shapes)",
                    "average_hash": "Average hash (good at crops, less tolerant of differences than perceptual hashing)",
                    "dhash": "Difference hash (similar to average hash, better at photos and art)"
                }
            },
            **({
                   "column": {
                       "help": "Dataset field",
                       "type": UserInput.OPTION_CHOICE,
                       "options": {
                           column: column
                           for column in columns}
                   }
               } if columns else {})
        }

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow processor to run on images downloaded from a dataset

        :param module: Module to determine compatibility with
        """
        return module.type.startswith("image-downloader")

    def process(self):
        column = self.parameters.get("column")
        hash_type = self.parameters.get("deduplicate")
        filename_filter = [".metadata.json"] if hash_type == "none" else []
        metadata = None
        hashed = 0

        # some maps to make sure we use the right value in the right place
        # url or filename, original image or duplicate, etc
        file_hash_map = {}
        hash_file_map = {}
        seen_hashes = set()
        id_file_map = {}

        for file in self.iterate_archive_contents(self.source_file, filename_filter=filename_filter):
            if file.name == ".metadata.json":
                with file.open() as infile:
                    try:
                        metadata = json.load(infile)
                        file_hash_map = {i: v["filename"] for i, v in metadata.items()} if self.parameters.get("image-value") == "url" else {i["filename"]: i["filename"] for i in metadata.values()}
                    except json.JSONDecodeError:
                        pass
            else:
                try:
                    hashed += 1
                    if hashed % 100 == 0:
                        self.dataset.update_status(f"Generated identity hashes for {hashed:,} of {self.source_dataset.num_rows-1:,} item(s)")
                    self.dataset.update_progress(hashed / (self.source_dataset.num_rows-1) * 0.5)
                    file_hash = hash_file(file, hash_type)
                    file_hash_map[file.name] = file_hash
                    if file_hash not in hash_file_map:
                        hash_file_map[file_hash] = file.name

                except (FileNotFoundError, ValueError) as e:
                    continue

        if not metadata:
            return self.dataset.finish_with_error("No valid metadata found in image archive - this processor can only "
                                                  "be run on sets of images sourced from another 4CAT dataset.")

        file_url_map = {v["filename"]: u for u, v in metadata.items()}
        for url, details in metadata.items():
            for item_id in details.get("post_ids", []):
                id_file_map[item_id] = details["filename"]

        root_dataset = None
        for parent in reversed(self.dataset.get_genealogy()):
            if parent.get_columns():
                root_dataset = parent
                break

        if not root_dataset:
            return self.dataset.finish_with_error("No suitable parent dataset found - this processor can only "
                                                  "be run on sets of images sourced from another 4CAT dataset.")

        network = nx.DiGraph()
        processed = 0
        for item in root_dataset.iterate_items():
            progress = processed / root_dataset.num_rows
            if hashed:
                # if hashing was necessary, we approximate that as 50% of the work
                progress = (progress * 0.5) + 0.5

            self.dataset.update_progress(progress)
            processed += 1
            if processed % 100 == 0:
                self.dataset.update_status(f"Processed {processed:,} of {root_dataset.num_rows:,} item(s)")

            if self.interrupted:
                raise ProcessorInterruptedException()

            if item.get("id") not in id_file_map:
                continue

            from_node_label = item.get(column)
            from_node = f"{column}-{from_node_label}"

            image_file = id_file_map[item.get("id")]
            image_hash = file_hash_map[image_file]
            if image_hash in seen_hashes:
                to_node_label = hash_file_map[image_hash]
                if image_file != to_node_label:
                    self.dataset.update_status(f"Image {image_file} is a duplicate of {to_node_label} - merging.")

            else:
                seen_hashes.add(image_hash)
                to_node_label = id_file_map[item.get("id")]

            if self.parameters.get("image-value") == "url":
                to_node_label = file_url_map[to_node_label]

            to_node = f"image-{to_node_label}"
            if from_node not in network.nodes:
                network.add_node(from_node, label=from_node_label, category=column)

            if to_node not in network.nodes:
                network.add_node(to_node, label=to_node_label, category="image", image=to_node_label)

            edge = (from_node, to_node)
            if edge not in network.edges():
                network.add_edge(*edge, frequency=0)

            network.edges[edge]["frequency"] += 1

        self.dataset.update_status("Writing network file")
        nx.write_gexf(network, self.dataset.get_results_path())
        self.dataset.finish(len(network.nodes))
