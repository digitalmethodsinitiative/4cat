"""
Google Vision API co-label network
"""
from backend.lib.processor import BasicProcessor
from common.lib.helpers import UserInput
from common.lib.exceptions import ProcessorInterruptedException

import networkx as nx

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class VisionTagNetworker(BasicProcessor):
    """
    Google Vision API co-label network
    """
    type = "vision-label-network"  # job type ID
    category = "Networks"  # category
    title = "Google Vision API Co-Label network"  # title displayed in UI
    description = "Create a GEXF network file comprised of all annotations returned by the" \
                  "Google Vision API. Labels returned by the API are nodes. Labels occurring on the same image form" \
                  "edges."
    extension = "gexf"  # extension of result file, used internally and in UI

    options = {
        "min_confidence": {
            "type": UserInput.OPTION_TEXT,
            "default": 0.5,
            "help": "Min confidence",
            "tooltip": "Value between 0 and 1; confidence required before the annotation is included. Note that the" \
                       "confidence is not known for all annotation types (these will be included with confidence '-1'" \
                       "in the output file)"
        },
        "include": {
            "type": UserInput.OPTION_MULTI,
            "options": {
                "labelAnnotations": "Label Detection",
                "landmarkAnnotations": "Landmark Detection",
                "logoAnnotations": "Logo Detection",
                "webDetection": "Web Detection",
                "localizedObjectAnnotations": "Object Localization"
            },
            "default": ["labelAnnotations", "landmarkAnnotations", "logoAnnotations", "webDetection", "localizedObjectAnnotations"],
            "help": "Features to map",
            "tooltip": "Note that only those features that were in the original API response can be mapped"
        }
    }

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow processor to run on Google Vision API data

        :param module: Module to determine compatibility with
        """
        return module.type == "google-vision-api"

    def process(self):
        """
        Generates a GDF co-annotation graph.
        """
        include = [*self.parameters.get("include", []), "file_name"]
        network_parameters = {"generated_by": "4CAT Capture & Analysis Toolkit",
                              "source_dataset_id": self.source_dataset.key}
        network = nx.Graph(**network_parameters)

        try:
            min_confidence = float(self.parameters.get("min_confidence", 0))
        except ValueError:
            min_confidence = 0

        for annotations in self.source_dataset.iterate_items(self):
            file_annotations = {}

            annotations = {atype: annotations[atype] for atype in include if atype in annotations}
            if not annotations:
                continue

            for annotation_type, tags in annotations.items():
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while processing Google Vision API output")

                if annotation_type == "file_name":
                    continue

                if annotation_type == "webDetection":
                    # handle web entities separately, since they're structured a bit
                    # differently
                    for entity in [e["description"] for e in tags.get("webEntities", []) if "description" in e]:
                        node_id = "webEntity:" + entity
                        file_annotations[node_id] = {"node_id": node_id, "category": "webEntity", "label": entity,
                                                     "confidence": -1}
                else:
                    # handle the other features here, since they all have a similar
                    # structure
                    short_type = annotation_type.split("Annotation")[0]
                    label_field = "name" if annotation_type == "localizedObjectAnnotations" else "description"
                    for tag in tags:
                        if min_confidence and "score" in tag and tag["score"] < min_confidence:
                            # skip if we're not so sure of the accuracy
                            continue
                        node_id = short_type + ":" + tag[label_field]
                        file_annotations[node_id] = {"node_id": node_id, "category": short_type, "label":
                            tag[label_field], "confidence": float(tag.get("score", -1))}

            # save with a label of the format 'landmark:Eiffel Tower'
            for node_id, annotation in file_annotations.items():
                if node_id not in network.nodes():
                    network.add_node(node_id, **annotation)

            # save pairs
            for from_annotation in file_annotations:
                for to_annotation in file_annotations:
                    if from_annotation == to_annotation:
                        continue

                    edge = (from_annotation, to_annotation)
                    if edge in network.edges():
                        network[from_annotation][to_annotation]["weight"] += 1
                    else:
                        network.add_edge(*edge, weight=1)

        nx.write_gexf(network, self.dataset.get_results_path())
        self.dataset.finish(len(network.nodes()))
