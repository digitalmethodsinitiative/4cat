"""
Convert Google Vision API annotations to CSV
"""
import csv

from backend.lib.processor import BasicProcessor

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)


class ConvertVisionOutputToCSV(BasicProcessor):
    """
    Convert Google Vision API annotations to CSV

    To avoid losing data, the output of the Vision API is initially saved as
    NDJSON, but it can be more useful to have a CSV file. This discards some
    information to allow 'flattening' the output to a simple CSV file.
    """
    type = "convert-google-vision-to-csv"  # job type ID
    category = "Conversion"  # category
    title = "Convert Vision results to CSV"  # title displayed in UI
    description = "Convert the Vision API output to a simplified CSV file."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Determine if processor is compatible with dataset

        :param module: Module to determine compatibility with
        """
        return module.type == "google-vision-api"

    def process(self):
        """
        This takes the NDJSON file as input and writes the same data as a CSV file
        """
        result = []
        annotation_types = set()
        done = 0
        self.dataset.update_status("Converting posts")

        if not self.source_file.exists():
            self.dataset.update_status("No data was returned by the Google Vision API, so none can be converted.", is_final=True)
            self.dataset.finish(0)
            return

        # recreate CSV file with the new dialect
        for annotations in self.source_dataset.iterate_items(self):
            file_result = {}

            # special case format
            if "webDetection" in annotations and annotations["webDetection"]:
                file_result["labelGuess"] = [l["label"] for l in annotations["webDetection"].get("bestGuessLabels", [])]
                file_result["webEntities"] = [e["description"] for e in annotations["webDetection"].get("webEntities", []) if "description" in e]
                file_result["urlsPagesWithMatchingImages"] = [u["url"] for u in annotations["webDetection"].get("pagesWithMatchingImages", [])]
                file_result["urlsMatchingImages"] = [u["url"] for u in annotations["webDetection"].get("fullMatchingImages", [])]
                file_result["urlsPartialMatchingImages"] = [u["url"] for u in annotations["webDetection"].get("partialMatchingImages", [])]

            # shared format
            for annotation_type, tags in annotations.items():
                if annotation_type not in ("landmarkAnnotations", "logoAnnotations", "labelAnnotations",
                                           "fullTextAnnotation", "localizedObjectAnnotations"):
                    # annotations that don't make sense to include
                    continue

                annotation_types.add(annotation_type)

                # retain only the label of the annotation
                if annotation_type == "fullTextAnnotation":
                    # this is not a list, just a single string containing the OCR'd text
                    file_result[annotation_type] = tags["text"]
                else:
                    # create a list of detected labels - can be imploded later
                    file_result[annotation_type] = set()
                    label_field = "name" if annotation_type == "localizedObjectAnnotations" else "description"

                    for tag in tags:
                        if annotation_type != "fullTextAnnotation":
                            file_result[annotation_type].add(tag[label_field])

            # flatten lists
            # note: may need a more elaborate approach, if labels can contain commas...
            for key, value in file_result.items():
                if type(value) is set:
                    file_result[key] = ",".join(value)

            result.append({"image_file": annotations["file_name"], **file_result})

            done += 1
            if done % 25 == 0:
                self.dataset.update_status("Processed %i/%i image files" % (done, self.source_dataset.num_rows))
                self.dataset.update_progress(done / self.source_dataset.num_rows)

        for index, value in enumerate(result):
            result[index] = {**{annotation_type: "" for annotation_type in annotation_types}, **value}

        self.write_csv_items_and_finish(result)
