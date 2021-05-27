"""
Request tags and labels from the Google Vision API for a given set of images
"""
import json
import csv

from tensorflow.keras.preprocessing import image
from tensorflow.keras.applications import Xception
from tensorflow.keras.applications.xception import preprocess_input, decode_predictions
import numpy as np

from common.lib.helpers import UserInput, convert_to_int
from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"

# What's this do?
csv.field_size_limit(1024 * 1024 * 1024)


class XceptionImageClassifier(BasicProcessor):
    """
    Xception Image Classifier

    Request tags and labels from the Xception prebuilt classification model in
    the Keras Application library model for a given set of images.
    """
    type = "xception_image_classification"  # job type ID
    category = "Metrics"  # category
    title = "Xception Image Classification"  # title displayed in UI
    description = """
    Uses the Xception Image Classification prebuilt model to annotate images
    with labels (1000 based on the ImageNet dataset) identified via machine
    learning. One request will be made per image.
    """ # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    accepts = ["image-downloader"]  # query types this post-processor accepts as input

    references = [
        "[Keras Application Xception Documentation](https://keras.io/api/applications/xception/)",
    ]

    input = "zip"
    output = "ndjson"

    options = {
        "amount": {
            "type": UserInput.OPTION_TEXT,
            "help": "Images to process (0 = all)",
            "default": 0
        },
        "features": {
            "type": UserInput.OPTION_MULTI,
            "help": "Features",
            "options": {
                "LABEL_DETECTION": "Label Detection",
                "TEXT_DETECTION": "Text Detection",
                "DOCUMENT_TEXT_DETECTION": "Document Text Detection",
                "SAFE_SEARCH_DETECTION": "Safe Search Detection",
                "FACE_DETECTION": "Facial Detection",
                "LANDMARK_DETECTION": "Landmark Detection",
                "LOGO_DETECTION": "Logo Detection",
                "IMAGE_PROPERTIES": "Image Properties",
                "CROP_HINTS": "Crop Hints",
                "WEB_DETECTION": "Web Detection",
                "OBJECT_LOCALIZATION": "Object Localization"
            },
            "default": ["LABEL_DETECTION"]
        }
    }

    def process(self):
        """
        This takes a 4CAT results file as input, and outputs a new CSV file
        with one column with image hashes, one with the first file name used
        for the image, and one with the amount of times the image was used
        """
        features = self.parameters.get("features")
        features = [{"type": feature} for feature in features]

        # Load in model
        model = Xception(include_top=True,
                         weights="imagenet",
                         input_tensor=None,
                         input_shape=None,
                         pooling=None,
                         classes=1000,
                         classifier_activation="softmax",
                         )


        max_images = convert_to_int(self.parameters.get("amount", 0), 100)
        total = self.source_dataset.num_rows if not max_images else min(max_images, self.source_dataset.num_rows)
        done = 0

        for image_file in self.iterate_archive_contents(self.source_file):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while processing Xception Image Classifications")

            done += 1
            self.dataset.update_status("Annotating image %i/%i" % (done, total))

            annotations = self.annotate_image(image_file, model, features)

            if not annotations:
                continue

            annotations = {"file_name": image_file.name, **annotations}

            with self.dataset.get_results_path().open("a", encoding="utf-8") as outfile:
                outfile.write(json.dumps(str(annotations)) + "\n")

            if max_images and done >= max_images:
                break

        self.dataset.update_status("Annotations retrieved for %i images" % done)
        self.dataset.finish(done)

    def annotate_image(self, image_file, model, features):
        """
        Get labels from the Xception Image Classifier

        :param Path image_file:  Path to file to annotate
        :param str api_key:  API Bearer Token
        :param list features:  Features to request
        :return dict:  Lists of detected features, one key for each feature
        """
        # Preprocess image
        img1 = image.load_img(image_file, target_size=(299, 299))
        x = image.img_to_array(img1)
        x = np.expand_dims(x, axis=0)
        x = preprocess_input(x)

        # Use model to make predictions
        preds = model.predict(x)
        # Decode predictions into labels
        preds = decode_predictions(preds, top=5)[0]

        # Return as dict
        return {'predictions' : [{'class' : prediction[0], 'description' : prediction[1], 'probability' : prediction[2]} for prediction in preds]}
