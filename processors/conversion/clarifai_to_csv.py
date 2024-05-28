"""
Convert Clarifai annotations to CSV
"""
import csv

from backend.lib.processor import BasicProcessor

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)


class ConvertClarifaiOutputToCSV(BasicProcessor):
    """
    Convert Clarifai annotations to CSV

    To avoid losing data, the output of the Clarifai API is initially saved as
    NDJSON, but it can be more useful to have a CSV file. This discards some
    information to allow 'flattening' the output to a simple CSV file.
    """
    type = "convert-clarifai-vision-to-csv"  # job type ID
    category = "Conversion"  # category
    title = "Convert Clarifai results to CSV"  # title displayed in UI
    description = "Convert the Clarifai API output to a simplified CSV file."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Determine if processor is compatible

        :param module: Module determine compatibility with
        """
        return module.type == "clarifai-api"

    def process(self):
        """
        This takes the NDJSON file as input and writes the same data as a CSV file
        """
        result = []
        done = 0

        if not self.source_file.exists():
            self.dataset.update_status("No data was returned by the Clarifai API, so none can be converted.", is_final=True)
            self.dataset.finish(0)
            return

        # recreate CSV file with the new dialect
        for annotations in self.source_dataset.iterate_items(self):
            for model, model_annotations in annotations.items():
                if model == "image":
                    continue

                result.append(
                    {
                        "image": annotations["image"],
                        "concepts": ", ".join(model_annotations.keys()),
                        "confidences": ", ".join([str(c) for c in model_annotations.values()]),
                        "model": model
                    }
                )

            done += 1
            if done % 25 == 0:
                self.dataset.update_status("Processed %i/%i image files" % (done, self.source_dataset.num_rows))
                self.dataset.update_progress(done / self.source_dataset.num_rows)

        self.write_csv_items_and_finish(result)
