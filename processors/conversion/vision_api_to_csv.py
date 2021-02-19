"""
Convert Google Vision API annotations to CSV
"""
import csv

from backend.abstract.processor import BasicProcessor
from backend.lib.exceptions import ProcessorInterruptedException

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
    type = "convert-vision-to-csv"  # job type ID
    category = "Conversion"  # category
    title = "Convert to CSV"  # title displayed in UI
    description = "Convert the Vision API output to a simplified CSV file."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    # all post-processors with CSV output
    accepts = ["google-vision-api"]

    input = "ndjson"
    output = "csv"

    def process(self):
        """
        This takes the NDJSON file as input and writes the same data as a CSV file
        """
        result = []
        annotation_types = set()
        done = 0
        self.dataset.update_status("Converting posts")

        # recreate CSV file with the new dialect
        for annotations in self.iterate_items(self.source_file):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while converting Vision API output")

            file_result = {}
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
                self.dataset.update_status("Processed %i/%i image files" % (done, self.parent.num_rows))

        for index, value in enumerate(result):
            result[index] = {**{annotation_type: "" for annotation_type in annotation_types}, **value}

        self.write_csv_items_and_finish(result)
