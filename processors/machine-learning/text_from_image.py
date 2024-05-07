"""
Request image text detection from DMI OCR server

The DMI OCR Server can be downloaded seperately here:
https://github.com/digitalmethodsinitiative/ocr_server#readme
and is run using the DMI Service Manager
"""
import requests
import json
import os

from common.config_manager import config
from common.lib.dmi_service_manager import DmiServiceManager, DsmOutOfMemory, DmiServiceManagerException
from common.lib.helpers import UserInput, convert_to_int
from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException, ProcessorException
from common.lib.item_mapping import MappedItem

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"

class ImageTextDetector(BasicProcessor):
    """
    Send images to DMI OCR server for OCR analysis
    """
    type = "text-from-images"  # job type ID
    category = "Conversion"  # category
    title = "Extract Text from Images"  # title displayed in UI
    description = """
    Uses optical character recognition (OCR) to extract text from images via machine learning.

    This processor first detects areas of an image that may contain text with the pretrained
    Character-Region Awareness For Text (CRAFT) detection model and then attempts to predict the
    text inside each area using Keras' implementation of a Convolutional Recurrent Neural
    Network (CRNN) for text recognition. Once words are predicted, an algorithm attempts to
    sort them into likely groupings based on locations within the original image.
    """
    extension = "ndjson"  # extension of result file, used internally and in UI

    references = [
        "[DMI OCR Server](https://github.com/digitalmethodsinitiative/ocr_server#readme)",
        "[Paddle OCR model](https://github.com/PaddlePaddle/PaddleOCR#readme)"
        "[Keras OCR model]( https://keras-ocr.readthedocs.io/en/latest/)",
        "[CRAFT text detection model](https://github.com/clovaai/CRAFT-pytorch)",
        "[Keras CRNN text recognition model](https://github.com/kurapan/CRNN)"
    ]

    config = {
        "dmi-service-manager.ea_ocr-intro-1": {
            "type": UserInput.OPTION_INFO,
            "help": "OCR (optical character recognition) allows text in images to be identified and extracted. Use our [prebuilt OCR image](https://github.com/digitalmethodsinitiative/ocr_server) with different available models.",
        },
        "dmi-service-manager.eb_ocr_enabled": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Enable OCR processor",
        },
    }

    options = {
        "amount": {
            "type": UserInput.OPTION_TEXT,
            "help": "Images to process (0 = all)",
            "default": 0,
            "coerce_type": int,
        },
        "model_type": {
            "type": UserInput.OPTION_CHOICE,
            "default": "paddle_ocr",
            "options": {
                "paddle_ocr": "Paddle OCR model",
                "keras_ocr": "Keras OCR model",
            },
            "help": "See references for additional information about models and their utility"
        },
        "update_original": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Update original database with detected text",
            "default": False,
            "tooltip": "If enabled, the original dataset will be modified to include a 'detected_text' column otherwise a seperate dataset will be created"
        }
    }

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow processor on image sets

        :param module: Module to determine compatibility with
        """
        return config.get('dmi-service-manager.eb_ocr_enabled', False, user=user) and \
               config.get("dmi-service-manager.ab_server_address", False, user=user) and \
               module.type.startswith("image-downloader")

    def process(self):
        """
        This takes a 4CAT zip file of images, and outputs a NDJSON file with the
        following structure:

        """
        if self.source_dataset.num_rows == 0:
            self.dataset.finish_with_error("No images available.")
            return

        # Unpack the images into a staging_area
        self.dataset.update_status("Unzipping images")

        if int(self.parameters.get("amount", 100)) != 0:
            max_images = int(self.parameters.get("amount", 100))
        else:
            max_images = None

        staging_area = self.dataset.get_staging_area()
        # Collect filenames and metadata
        image_filenames = []
        metadata_file = None
        for image in self.iterate_archive_contents(self.source_file, staging_area=staging_area, immediately_delete=False):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while unzipping images")

            if image.name.split('.')[-1] not in ["json", "log"]:
                image_filenames.append(image.name)

            if image.name == ".metadata.json":
                metadata_file = image.name

            if max_images and len(image_filenames) >= max_images:
                break

        total_image_files = len(image_filenames)

        # Make output dir
        output_dir = self.dataset.get_staging_area()

        # Initialize DMI Service Manager
        dmi_service_manager = DmiServiceManager(processor=self)

        # Results should be unique to this dataset
        server_results_folder_name = f"4cat_results_{self.dataset.key}"
        # Files can be based on the parent dataset (to avoid uploading the same files multiple times)
        file_collection_name = dmi_service_manager.get_folder_name(self.source_dataset)

        # Process the image files (upload to server if needed)
        path_to_files, path_to_results = dmi_service_manager.process_files(input_file_dir=staging_area,
                                                                           filenames=image_filenames,
                                                                           output_file_dir=output_dir,
                                                                           server_file_collection_name=file_collection_name,
                                                                           server_results_folder_name=server_results_folder_name)

        # Arguments for the OCR server
        data = {'args': ['--model', self.parameters.get("model_type"),
                         '--output_dir', f"data/{path_to_results}",
                         '--images']}
        data["args"].extend([f"data/{path_to_files.joinpath(dmi_service_manager.sanitize_filenames(filename))}" for filename in image_filenames])

        # Send request to DMI Service Manager
        self.dataset.update_status(f"Requesting service from DMI Service Manager...")
        api_endpoint = "ocr"
        try:
            dmi_service_manager.send_request_and_wait_for_results(api_endpoint, data, wait_period=30,
                                                                  check_process=True)
        except DsmOutOfMemory:
            self.dataset.finish_with_error(
                "DMI Service Manager ran out of memory; Try decreasing the number of images or try again or try again later.")
            return
        except DmiServiceManagerException as e:
            self.dataset.finish_with_error(str(e))
            return

        self.dataset.update_status("Processing OCR results...")
        # Download the result files if necessary
        dmi_service_manager.process_results(output_dir)

        # Load the metadata from the archive
        image_metadata = {}
        if metadata_file is None:
            try:
                self.extract_archived_file_by_name(".metadata.json", self.source_file, staging_area)
                metadata_exists = True
            except KeyError:
                self.dataset.update_status("No metadata file found")
                metadata_exists = False
        else:
            # Previously extracted
            metadata_exists = True

        if metadata_exists:
            with open(os.path.join(staging_area, '.metadata.json')) as file:
                image_data = json.load(file)
                for url, data in image_data.items():
                    if data.get('success'):
                        data.update({"url": url})
                        image_metadata[data['filename']] = data

        # Check if we need to collect data for updating the original dataset
        update_original = self.parameters.get("update_original", False)
        if update_original:
            if not metadata_exists:
                self.dataset.update_status("No metadata file found, cannot update original dataset")
                update_original = False
            else:
                # Create filename to post id mapping
                filename_to_post_id = {}
                for url, data in image_data.items():
                    if data.get('success'):
                        filename_to_post_id[data.get('filename')] = data.get('post_ids')
                post_id_to_results = {}

        # Save files as NDJSON, then use map_item for 4CAT to interact
        processed = 0
        with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile:
            for result_filename in os.listdir(output_dir):
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while writing results to file")

                self.dataset.log(f"Writing {result_filename}...")
                with open(output_dir.joinpath(result_filename), "r") as result_file:
                    result_data = json.loads(''.join(result_file))
                    image_name = result_data.get("filename")

                    # Collect annotations for updating the original dataset
                    if update_original:
                        # Need to include filename as there may be many images to a single post
                        detected_text = '%s:"""%s"""' % (image_name, result_data.get('simplified_text', {}).get('raw_text', ''))

                        post_ids = filename_to_post_id[image_name]
                        for post_id in post_ids:
                            # Posts can have multiple images
                            if post_id in post_id_to_results.keys():
                                post_id_to_results[post_id].append(detected_text)
                            else:
                                post_id_to_results[post_id] = [detected_text]

                    data = {
                        "id": image_name,
                        **result_data,
                        "image_metadata": image_metadata.get(image_name, {}) if image_metadata else {},
                    }
                    outfile.write(json.dumps(data) + "\n")

                    processed += 1
        self.dataset.update_status("Annotations retrieved for %i images" % processed)

        # Update the original dataset with the detected text if requested
        if update_original:
            self.dataset.update_status("Updating original dataset with annotations")

            # We need an entry for each row/item in the original dataset necitating we loop through it
            detected_text_column = []
            for post in self.dataset.top_parent().iterate_items(self):
                detected_text_column.append('\n'.join(post_id_to_results.get(post.get('id'), [])))

            try:
                self.add_field_to_parent(field_name='4CAT_detexted_text',
                                         new_data=detected_text_column,
                                         which_parent=self.dataset.top_parent())
            except ProcessorException as e:
                self.dataset.update_status("Error updating parent dataset: %s" % e)

        detected_message = f"Detected speech in {processed} of {total_image_files} images."
        if self.parameters.get("update_original", False) and not update_original:
            self.dataset.update_status(f"{detected_message} No metadata file found, unable to update original dataset.", is_final=True)
        else:
            self.dataset.update_status(detected_message)
        self.dataset.finish(processed)

    @staticmethod
    def map_item(item):
        """
        For preview frontend
        """
        return MappedItem({
            "filename": item.get("filename"),
            "model_type": item.get("model_type"),
            "text": item.get("simplified_text", {}).get("raw_text"),
            "post_ids": ", ".join([str(post_id) for post_id in item.get("image_metadata", {}).get("post_ids", [])]),
            "image_url": item.get("image_metadata", {}).get("url")
        })
