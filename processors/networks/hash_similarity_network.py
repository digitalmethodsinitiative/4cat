"""
Calculate similarity of hashes and create a GEXF network file.

Only supports bit based hashes currently (e.g., 101010101110110011)
"""
import networkx as nx
import numpy as np

from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorException
from common.lib.helpers import UserInput


__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class HashSimilarityNetworker(BasicProcessor):
    """
    Compare hashes and generate a network based on similarity
    """
    type = "hash-similarity-network"
    category = "Networks"
    title = "Hash Similarity network to identify near duplicate hashes"
    description = "Calculate similarity of hashes and create a GEXF network file."
    extension = "gexf"

    options = {
        "descriptor_column": {
            "help": "Column containing ID or unique descriptor (e.g., URL, filename, etc.)",
            "inline": True,
        },
        "choice_column": {
            "help": "Column containing hashes",
            "inline": True,
            "tooltip": "Expects all hashes to be of the same length"
        },
        "percent_similar": {
            "type": UserInput.OPTION_TEXT,
            "help": "Minimum percentage for connection",
            "tooltip": "Only create a connection if the two hashes are at least X percent similar (e.g. at least 75% of the two hashes must be identical). Use 0 to create weighted edges for all hash comparisons.",
            "coerce_type": int,
            "default": 90,
            "min": 0,
            "max": 100,
        },
    }

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        Update column option with actual columns
        """
        options = cls.options

        # Get the columns for the select columns option
        if parent_dataset and parent_dataset.get_columns():
            columns = parent_dataset.get_columns()
            options["choice_column"]["type"] = UserInput.OPTION_CHOICE
            options["choice_column"]["options"] = {v: v for v in columns}
            options["choice_column"]["default"] = "video_hash" if "video_hash" in columns else sorted(columns, key=lambda k: "hash" in k).pop()

            options["descriptor_column"]["type"] = UserInput.OPTION_CHOICE
            options["descriptor_column"]["options"] = {v: v for v in columns}
            options["descriptor_column"]["default"] = "id" if "id" in columns else sorted(columns, key=lambda k: "id" in k).pop()

        return options

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Currently only allowed on video-hashes, but technically any row of bit hashes will work. Could check for "hash"
        in columns, but... how to make that a check as a classmethod?
        """
        return module.type == "video-hashes"

    def process(self):
        """
        Takes a list of bit hashes and compares them. Then makes network file.
        """
        id_column = self.parameters.get("descriptor_column")
        column = self.parameters.get("choice_column")
        percent_similar = self.parameters.get("percent_similar")/100

        network_parameters = {"generated_by": "4CAT Capture & Analysis Toolkit",
                              "source_dataset_id": self.source_dataset.key}
        network = nx.Graph(**network_parameters)

        self.dataset.update_status("Collecting identifiers and hashes from dataset")
        collected = 0
        identifiers = []
        hashes = []
        hash_metadata = {}
        bit_length = None
        metadata_lists = None
        for item in self.source_dataset.iterate_items(self):
            if column not in item:
                self.dataset.update_status("Column %s not found in dataset" % column, is_final=True)
                self.dataset.finish(0)
                return

            # Process hash
            # TODO: process other types of hashes; currently only supporting bit hashes
            original_hash = item.pop(column)

            if type(original_hash) == str:
                item_hash = original_hash
                # Check if 0b starts string
                if '0b' == original_hash[:2]:
                    item_hash = original_hash[2:]
            else:
                self.dataset.update_status("Hash type %s currently not supported" % type(original_hash), is_final=True)
                self.dataset.finish(0)
                return

            try:
                item_hash = [int(bit) for bit in item_hash]
            except ValueError as e:
                self.dataset.update_status("Column %s not found in dataset" % column, is_final=True)
                self.dataset.finish(0)
                return

            if not all([bit == 1 or bit == 0 for bit in item_hash]):
                # Note: this technically allows [True, False, 0, 1] "hashes"
                self.dataset.update_status("Incorrect type of hash found in dataset (not a bit hash)", is_final=True)
                self.dataset.finish(0)
                return

            item_id = item.pop(id_column)

            if item_id is None or item_id in identifiers:
                self.dataset.update_status("ID Column is not unique for each hash", is_final=True)
                self.dataset.finish(0)
                return

            # All hashes should be the same length
            if bit_length is None:
                bit_length = len(item_hash)

            # Add only if hash exists
            if item_hash:
                if len(item_hash) == bit_length:
                    identifiers.append(item_id)
                    hashes.append(np.array(item_hash))

                    # Append any metadata associated with hash
                    # Convert any list or numbers for Gephi
                    if metadata_lists is None:
                        metadata_lists = []
                        metadata_numbers = []
                        for key, value in item.items():
                            if type(value) == list:
                                metadata_lists.append(key)
                            elif type(value) == str:
                                try:
                                    float(value)
                                    metadata_numbers.append(key)
                                except ValueError:
                                    pass
                    for key in metadata_lists:
                        item[key] = ','.join(item[key])
                    for key in metadata_numbers:
                        item[key] = float(item[key])

                    if 'post_ids' in item:
                        item.pop('post_ids')
                    hash_metadata[item_id] = item

                else:
                    self.dataset.update_status("Hashes are not compatible for comparison", is_final=True)
                    self.dataset.finish(0)

            collected += 1
            if collected % 500 == 0:
                self.dataset.update_status("Collected %i of %i data points" % (collected, self.source_dataset.num_rows))
                self.dataset.update_progress(collected / self.source_dataset.num_rows)

        if len(identifiers) != len(hashes):
            self.dataset.update_status("Mismatch in hashes and IDs", is_final=True)
            self.dataset.finish(0)

        self.dataset.update_status("Adding nodes to network")
        for node in identifiers:
            network.add_node(node, **hash_metadata[node])

        hashes = np.array(hashes)
        self.dataset.update_status("Comparing %i hashes with each other" % len(hashes))
        comparisons = 0
        expected_comparisons = np.math.comb(len(hashes), 2)
        for i, current_hash in enumerate(hashes):
            # Remove this hash from hashes (as previous calculations have already occured and it is unnecessary to
            # compare a hash to itself)
            hashes = hashes[1:]

            # Compare current hash
            xor_result = np.bitwise_xor(current_hash, hashes)

            # Add comparisons to network
            for j, xor_comparison in enumerate(xor_result):
                id1 = identifiers[i]
                # Node 2 is this iteration plus comparison number PLUS one as the first hash of this set has been
                # removed (e.g., very first ID2 is 0+0+1)
                id2 = identifiers[i+j+1]

                # Check if edge exists (it shouldn't!)
                edge = (id1, id2)
                if edge in network.edges():
                    raise ProcessorException('Error in processing hash similarities')

                # Check if xor_comparison is less than requested similarity
                # xor compares each bit and returns 0 if a bit is the same and 1 if different
                edge_percent_similar = 1 - (xor_comparison.sum() / bit_length)
                if edge_percent_similar > percent_similar:
                    network.add_edge(id1, id2, weight=edge_percent_similar)

                comparisons += 1
                if comparisons % 500 == 0:
                    self.dataset.update_status(
                        "Calculated %i of %i hash similarities" % (comparisons, expected_comparisons))
                    self.dataset.update_progress(comparisons / expected_comparisons)

        if not network.edges():
            self.dataset.update_status("No edges could be created for the given parameters", is_final=True)
            self.dataset.finish(0)
            return

        self.dataset.update_status("Writing network file")

        nx.write_gexf(network, self.dataset.get_results_path())
        self.dataset.finish(len(network.nodes))
