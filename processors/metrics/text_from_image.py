"""
Request image text detection from DMI OCR server
"""
import requests
import json
import os

import common.config_manager as config
from common.lib.helpers import UserInput, convert_to_int
from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException, ProcessorException

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"

class ImageTextDetector(BasicProcessor):
    """
    Send images to DMI OCR server for OCR analysis
    """
    type = "text-from-images"  # job type ID
    category = "Post metrics"  # category
    title = "Extract Text from Images"  # title displayed in UI
    description = """
    Uses optical character recognition (OCR) to extract text from images via machine learning.
    
    This processor first detects areas of an image that may contain text with the pretrained 
    Character-Region Awareness For Text (CRAFT) detection model and then attempts to predict the
    text inside each area using Keras' implementation of a Convolutional Recurrent Neural 
    Network (CRNN) for text recognition. Once words are predicted, an algorythm attempts to
    sort them into likely groupings based on locations within the original image.
    """
    extension = "ndjson"  # extension of result file, used internally and in UI

    references = [
        "[Keras OCR Documentation]( https://keras-ocr.readthedocs.io/en/latest/)",
        "[CRAFT text detection model](https://github.com/clovaai/CRAFT-pytorch)",
        "[Keras CRNN text recognition model](https://github.com/kurapan/CRNN)"
    ]

    config = {
        "text_from_images.DMI_OCR_SERVER": {
            "type": UserInput.OPTION_TEXT,
            "default": "",
            "help": "URL to the DMI OCR server",
            "tooltip": "URL to the [DMI OCR server](https://github.com/digitalmethodsinitiative/ocr_server); e.g. http://pixplot.digitalmethods.net/ocr/",
        }
    }

    options = {
        "amount": {
            "type": UserInput.OPTION_TEXT,
            "help": "Images to process (0 = all)",
            "default": 0
        },
        "update_original": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Update original database with detected text",
            "default": False,
            "tooltip": "If enabled, the original dataset will be modified to include a 'detected_text' column otherwise a seperate dataset will be created"
        }
    }

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Allow processor on image sets

        :param module: Dataset or processor to determine compatibility with
        """
        return module.type.startswith("image-downloader") and config.get('text_from_images.DMI_OCR_SERVER', False)

    def process(self):
        """
        This takes a 4CAT zip file of images, and outputs a NDJSON file with the
        following structure:

        """
        max_images = convert_to_int(self.parameters.get("amount", 0), 100)
        total = self.source_dataset.num_rows if not max_images else min(max_images, self.source_dataset.num_rows)
        done = 0

        # Check if we need to collect data for updating the original dataset
        update_original = self.parameters.get("update_original", False)
        if update_original:
            # We need to unpack the archive to get the metadata
            staging_area = self.unpack_archive_contents(self.source_file)
            # Load the metadata from the archive
            with open(os.path.join(staging_area, '.metadata.json')) as file:
                image_data = json.load(file)
                filename_to_post_id = {}
                for url, data in image_data.items():
                    if data.get('success'):
                        filename_to_post_id[data.get('filename')] = data.get('post_ids')
                del image_data

            # And something to store the results
            post_id_to_results = {}
        else:
            staging_area = None

        for image_file in self.iterate_archive_contents(self.source_file, staging_area=staging_area):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while fetching data from Google Vision API")

            done += 1
            self.dataset.update_status("Annotating image %i/%i" % (done, total))
            self.dataset.update_progress(done / total)

            annotations = self.annotate_image(image_file)

            if not annotations:
                continue

            annotations = {"file_name": image_file.name, **annotations}

            # Collect annotations for updating the original dataset
            if update_original:
                # Need to include filename as there may be many images to a single post
                detected_text = '%s:"""%s"""' % (image_file.name, annotations.get('simplified_text', {}).get('raw_text', ''))

                post_ids = filename_to_post_id[image_file.name]
                for post_id in post_ids:
                    # Posts can have multiple images
                    if post_id in post_id_to_results.keys():
                        post_id_to_results[post_id].append(detected_text)
                    else:
                        post_id_to_results[post_id] = [detected_text]

            with self.dataset.get_results_path().open("a", encoding="utf-8") as outfile:
                outfile.write(json.dumps(annotations) + "\n")

            if max_images and done >= max_images:
                break

        self.dataset.update_status("Annotations retrieved for %i images" % done)

        # Update the original dataset with the detected text if requested
        if update_original:
            self.dataset.update_status("Updating original dataset with annotations")

            # We need an entry for each row/item in the original dataset necitating we loop through it
            detected_text_column = []
            for post in self.dataset.top_parent().iterate_items(self):
                detected_text_column.append('\n'.join(post_id_to_results.get(post.get('id'), [])))

            try:
                self.add_field_to_parent(field_name='detexted_text',
                                         new_data=detected_text_column,
                                         which_parent=self.dataset.top_parent())
            except ProcessorException as e:
                self.dataset.update_status("Error updating parent dataset: %s" % e)

        self.dataset.finish(done)

    def annotate_image(self, image_file):
        """
        Get annotations from the DMI OCR server

        :param Path image_file:  Path to file to annotate
        :return dict:  Lists of detected features, one key for each feature
        """
        server = config.get('text_from_images.DMI_OCR_SERVER', '')

        if not server:
            raise ProcessorException('DMI OCR server not configured')

        with image_file.open("rb") as infile:
            try:
                api_request = requests.post(server + 'api/detect_text', files={'image': infile})
            except (requests.RequestException, ConnectionError) as e:
                self.dataset.update_status("Skipping image %s due to %s (%s)" % (image_file.name, e.__name__, str(e)))
                return None

        if api_request.status_code != 200:
            self.dataset.update_status("Got response code %i from DMI OCR server for image %s: %s" % (api_request.status_code, image_file.name, api_request.content))
            return None

        try:
            response = api_request.json()
        except (json.JSONDecodeError, KeyError):
            self.dataset.update_status("Got an improperly formatted response from DMI OCR server for image %s, skipping" % image_file.name)
            return None

        return response
