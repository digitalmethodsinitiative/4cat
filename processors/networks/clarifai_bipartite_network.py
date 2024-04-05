"""
Google Vision API co-label network
"""
from backend.lib.processor import BasicProcessor
from common.lib.helpers import UserInput

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

import networkx as nx


class VisionTagBiPartiteNetworker(BasicProcessor):
    """
    Google Vision API co-label network
    """
    type = "clarifai-bipartite-network"  # job type ID
    category = "Networks"  # category
    title = "Clarifai Bipartite Annotation Network"  # title displayed in UI
    description = "Create a GEXF network file comprised of all annotations returned by the Clarifai API. Labels " \
                  "returned by the API, and image file names, are nodes. Edges are created between file names and " \
                  "labels if the label occurs for the image with that file name."
    extension = "gexf"  # extension of result file, used internally and in UI

    options = {
        "min_confidence": {
            "type": UserInput.OPTION_TEXT,
            "default": 0.5,
            "help": "Min confidence",
            "tooltip": "Value between 0 and 1; confidence required before the annotation is included. Note that the" \
                       "confidence is not known for all annotation types (these will be included with confidence '-1'" \
                       "in the output file)"
        }
    }

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow processor to run on Google Vision API data

        :param module: Module to determine compatibility with
        """
        return module.type == "clarifai-api"

    def process(self):
        """
        Generates a GEXF file-annotation graph.
        """
        network_parameters = {"generated_by": "4CAT Capture & Analysis Toolkit",
                              "source_dataset_id": self.source_dataset.key}
        network = nx.DiGraph(**network_parameters)

        try:
            min_confidence = float(self.parameters.get("min_confidence", 0))
        except ValueError:
            min_confidence = 0

        for annotations in self.source_dataset.iterate_items(self):
            image_id = "image-" + annotations["image"]
            network.add_node(image_id, label=annotations["image"], type="image", annotation_type="")
            for model, concepts in annotations.items():
                if model in ("combined", "image"):
                    continue

                for concept, confidence in concepts.items():
                    try:
                        confidence = float(confidence)
                    except TypeError:
                        confidence = 0

                    if confidence < min_confidence:
                        continue

                    node_id = model + "-" + concept
                    if concept not in network.nodes():
                        network.add_node(node_id, label=concept, confidence=confidence, type="annotation", annotation_type=model)

                    network.add_edge(image_id, node_id)

        nx.write_gexf(network, self.dataset.get_results_path())
        self.dataset.finish(len(network.nodes()))
