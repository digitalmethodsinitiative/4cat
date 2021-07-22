"""
Google Vision API co-label network
"""
from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput, gdf_escape
from common.lib.exceptions import ProcessorInterruptedException

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
    title = "Google Vision API Label network"  # title displayed in UI
    description = "Create a Gephi-compatible network comprised of all annotations returned for a set of images by the" \
                  "Google Vision API. Labels returned by the API are nodes; labels occurring on the same image form" \
                  "edges, weighted by the amount of co-tag occurrences."
    extension = "gdf"  # extension of result file, used internally and in UI

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
    def is_compatible_with(cls, module=None):
        """
        Allow processor to run on Google Vision API data

        :param module: Dataset or processor to determine compatibility with
        """
        return module.type == "google-vision-api"

    def process(self):
        """
        Generates a GDF co-annotation graph.
        """
        include = [*self.parameters.get("include", []), "file_name"]
        print(include)
        pair_separator = ":::::"
        nodes = {}
        edges = {}

        try:
            min_confidence = float(self.parameters.get("min_confidence", 0))
        except ValueError:
            min_confidence = 0

        for annotations in self.iterate_items(self.source_file):
            file_annotations = []

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
                        file_annotations.append({"type"
                                                 : "webEntity", "label": entity, "confidence": -1})
                else:
                    # handle the other features here, since they all have a similar
                    # structure
                    short_type = annotation_type.split("Annotation")[0]
                    label_field = "name" if annotation_type == "localizedObjectAnnotations" else "description"
                    for tag in tags:
                        if min_confidence and "score" in tag and tag["score"] < min_confidence:
                            # skip if we're not so sure of the accuracy
                            continue
                        file_annotations.append(
                            {"type": short_type, "label": tag[label_field], "confidence": float(tag.get("score", -1))})

            # save with a label of the format 'landmark:Eiffel Tower'
            for annotation in file_annotations:
                label = "%s:%s" % (annotation["type"], annotation["label"])
                if label not in nodes:
                    nodes[label] = annotation

            # save pairs
            for from_annotation in file_annotations:
                for to_annotation in file_annotations:
                    if from_annotation == to_annotation:
                        continue

                    from_label = "%s:%s" % (from_annotation["type"], from_annotation["label"])
                    to_label = "%s:%s" % (to_annotation["type"], to_annotation["label"])
                    pair = sorted([from_label, to_label])  # sorted, because not directional
                    pair = pair_separator.join(pair)

                    if pair not in edges:
                        edges[pair] = 0

                    edges[pair] += 1

        # write GDF file
        self.dataset.update_status("Writing to Gephi-compatible file")
        with self.dataset.get_results_path().open("w", encoding="utf-8") as results:
            results.write("nodedef>name VARCHAR,label VARCHAR,category VARCHAR\n")
            for node_id, node in nodes.items():
                results.write("%s,%s,%s\n" % (gdf_escape(node_id), gdf_escape(node["label"]), gdf_escape(node["type"])))

            results.write("edgedef>from VARCHAR, to VARCHAR, weight INTEGER\n")
            for edge, weight in edges.items():
                pair = edge.split(pair_separator)
                results.write("%s,%s,%i\n" % (gdf_escape(pair[0]), gdf_escape(pair[1]), weight))

        self.dataset.finish(len(nodes))
