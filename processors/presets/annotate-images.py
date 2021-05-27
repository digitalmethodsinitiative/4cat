"""
Annotate top images
"""
from backend.abstract.preset import ProcessorPreset

from common.lib.helpers import UserInput, convert_to_int


class AnnotateImages(ProcessorPreset):
    """
    Run processor pipeline to annotate images
    """
    type = "preset-annotate-images"  # job type ID
    category = "Presets"  # category. 'Presets' are always listed first in the UI.
    title = "Annotate images with Google Vision API"  # title displayed in UI
    description = "Use the Google Vision API to annotate images linked to in the dataset the most often. Note that " \
                  "the Google Vision API is a paid service and using this processor will count towards your Google " \
                  "API credit!"
    extension = "csv"

    references = [
        "[Google Vision API Documentation](https://cloud.google.com/vision/docs)",
        "[Google Vision API Pricing & Free Usage Limits](https://cloud.google.com/vision/pricing)"
    ]

    options = {
        "amount": {
            "type": UserInput.OPTION_TEXT,
            "help": "Images to process (0 = all)",
            "default": 10,
            "tooltip": "Setting this to 0 (process all images) is NOT recommended unless you have infinite Google API"
                       " credit."
        },
        "api_key": {
            "type": UserInput.OPTION_TEXT,
            "help": "API Key",
            "tooltip": "The API Key for the Google API account you want to query with. You can generate and find this"
                       "key on the API dashboard."
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

    def get_processor_pipeline(self):
        """
        This queues a series of post-processors to annotate images

        First, the required amount of images referenced in the dataset is
        downloaded, in order of most-referenced; then, the requested
        features are extracted using the Google Vision API; finally, the result
        is converted to a CSV file for easy processing.
        """
        amount = convert_to_int(self.parameters.get("amount", 10), 10)
        api_key = self.parameters.get("api_key", "")
        features = self.parameters.get("features", "")

        self.dataset.delete_parameter("api_key")  # sensitive, delete as soon as possible

        pipeline = [
            # first, extract top images
            {
                "type": "top-images",
                "parameters": {
                    "overwrite": False
                }
            },
            # then, download the images we want to annotate
            {
                "type": "image-downloader",
                "parameters": {
                    "amount": amount,
                    "overwrite": False
                }
            },
            # then, annotate the downloaded images with the Google Vision API
            {
                "type": "google-vision-api",
                "parameters": {
                    "features": features,
                    "amount": amount,
                    "api_key": api_key
                }
            },
            # finally, create a simplified CSV file from the download NDJSON (which can also be retrieved later)
            {
                "type": "convert-vision-to-csv",
                "parameters": {}
            }
        ]

        return pipeline
