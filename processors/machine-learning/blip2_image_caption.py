"""
OpenAI CLIP categorize images
"""
import os
import json


from backend.lib.processor import BasicProcessor
from common.lib.dmi_service_manager import DmiServiceManager, DmiServiceManagerException, DsmOutOfMemory
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.user_input import UserInput
from common.config_manager import config
from common.lib.item_mapping import MappedItem

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class CategorizeImagesCLIP(BasicProcessor):
    """
    Caption Images with OpenAI BLIP2
    """
    type = "image-captions"  # job type ID
    category = "Visual"  # category
    title = "Generate image captions using OpenAI's BLIP2 model"  # title displayed in UI
    description = "The BLIP2 model uses a pretrained image encoder combined with an LLM to generate image captions. The model can also be prompted and uses the image plus prompt to generate text responses."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI

    references = [
        "[OpenAI CLIP blog](https://openai.com/research/clip)",
        "[BLIP-2 paper: Bootstrapping Language-Image Pre-training with Frozen Image Encoders and Large Language Models](https://arxiv.org/abs/2301.12597)",
        "[BLIP-2 documentation](https://huggingface.co/docs/transformers/main/model_doc/blip-2)",
        ]

    config = {
        "dmi-service-manager.fb_blip2-intro-1": {
            "type": UserInput.OPTION_INFO,
            "help": "OpenAI's BLIP-2 model generates image captions using a LLM. Ensure the DMI Service Manager is running and has a [prebuilt BLIP2 image](https://github.com/digitalmethodsinitiative/dmi_dockerized_services/tree/main/blip2).",
        },
        "dmi-service-manager.fc_blip2_enabled": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Enable BLIP-2 Image Caption Generation",
        },
        "dmi-service-manager.fd_blip2_num_files": {
            "type": UserInput.OPTION_TEXT,
            "coerce_type": int,
            "default": 0,
            "help": "BLIP-2 max number of images",
            "tooltip": "Use '0' to allow unlimited number"
        },
    }

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow on image archives if enabled in Control Panel
        """
        return config.get("dmi-service-manager.fc_blip2_enabled", False, user=user) and \
               config.get("dmi-service-manager.ab_server_address", False, user=user) and \
               module.type.startswith("image-downloader")

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        Collect maximum number of files from configuration and update options accordingly
        """
        options = {
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "coerce_type": int,
            },
            "prompt": {
                "type": UserInput.OPTION_TEXT,
                "help": "Optional prompt to use with image",
                "tooltip": "Leave blank to generate image captions; prompting can create wildly different results so test on small batches first",
                "default": "",
            },
            "max_new_tokens": {
                "type": UserInput.OPTION_TEXT,
                "help": "Number of tokens of text to return",
                "default": 20,
                "max": 100, # stopping potential insanity; arbitrary and up for debate/testing
                "coerce_type": int,
                "tooltip": "Recommend 10-50 tokens for image captions; more tokens may be less accurate and repeat information",
            }
        }

        # Update the amount max and help from config
        max_number_images = int(config.get("dmi-service-manager.fd_blip2_num_files", 100, user=user))
        if max_number_images == 0:  # Unlimited allowed
            options["amount"]["help"] = "Number of images"
            options["amount"]["default"] = 100
            options["amount"]["min"] = 0
            options["amount"]["tooltip"] = "Use '0' to categorize all images (this can take a very long time)"
        else:
            options["amount"]["help"] = f"Number of images (max {max_number_images})"
            options["amount"]["default"] = min(max_number_images, 100)
            options["amount"]["max"] = max_number_images
            options["amount"]["min"] = 1

        return options

    def process(self):
        """
        This takes a zipped set of image files and uses a CLIP docker image to categorize them.
        """
        if self.source_dataset.num_rows <= 1:
            # 1 because there is always a metadata file
            self.dataset.finish_with_error("No images found.")
            return

        # Unpack the image files into a staging_area
        self.dataset.update_status("Unzipping image files")
        staging_area = self.dataset.get_staging_area()
        total_image_files = 0
        image_filenames = []
        for file in self.iterate_archive_contents(self.source_file, staging_area=staging_area, immediately_delete=False):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while unpacking archive")

            if file.name.split('.')[-1] not in ["json", "log"]:
                image_filenames.append(file.name)
                total_image_files += 1

            if self.parameters.get("amount", 100) != 0 and total_image_files >= self.parameters.get("amount", 100):
                break

        # Make output dir
        output_dir = self.dataset.get_staging_area()

        # Initialize DMI Service Manager
        dmi_service_manager = DmiServiceManager(processor=self)

        # Check connection and GPU memory available
        try:
            gpu_response = dmi_service_manager.check_gpu_memory_available("blip2")
        except DmiServiceManagerException as e:
            return self.dataset.finish_with_error(str(e))

        if int(gpu_response.get("memory", {}).get("gpu_free_mem", 0)) < 1000000:
            self.dataset.finish_with_error(
                "DMI Service Manager currently busy; no GPU memory available. Please try again later.")
            return

        # Results should be unique to this dataset
        results_folder_name = f"texts_{self.dataset.key}"
        # Files can be based on the parent dataset (to avoid uploading the same files multiple times)
        file_collection_name = dmi_service_manager.get_folder_name(self.source_dataset)

        path_to_files, path_to_results = dmi_service_manager.process_files(staging_area, image_filenames, output_dir,
                                                                           file_collection_name, results_folder_name)

        # BLIP2 args
        data = {"args": [
                        "--output-dir", f"data/{path_to_results}",
                        "--image-folder", f"data/{path_to_files}",
                        "--max_new_tokens", str(self.parameters.get("max_new_tokens", 20)),
                        "--dataset-name", f"{self.dataset.key}"
                         ]
                }

        # If prompt, add to args
        if self.parameters.get("prompt"):
            data["args"].extend(["--prompt", self.parameters.get("prompt")])

        # Send request to DMI Service Manager
        self.dataset.update_status(f"Requesting service from DMI Service Manager...")
        api_endpoint = "blip2"
        try:
            dmi_service_manager.send_request_and_wait_for_results(api_endpoint, data, wait_period=30)
        except DsmOutOfMemory:
            self.dataset.finish_with_error(
                "DMI Service Manager ran out of memory; Try decreasing the number of images or try again or try again later.")
            return
        except DmiServiceManagerException as e:
            self.dataset.finish_with_error(str(e))
            return

        # Load the video metadata if available
        image_metadata = {}
        metadata_file = self.extract_archived_file_by_name(".metadata.json", self.source_file, staging_area)
        if metadata_file:
            with open(metadata_file) as file:
                image_data = json.load(file)
                self.dataset.log("Found and loaded image metadata")
                for url, data in image_data.items():
                    if data.get('success'):
                        data.update({"url": url})
                        # using the filename without extension as the key; since that is how the results form their filename
                        image_metadata[".".join(data['filename'].split(".")[:-1])] = data

        self.dataset.update_status("Processing BLIP2 results...")
        # Download the result files
        dmi_service_manager.process_results(output_dir)
        self.dataset.log(f"result files: {list(output_dir.glob('*'))}")

        # If metadata, add it to our result file
        processed = 0
        with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile:
            # Should be one result file in the output directory
            with open(output_dir.joinpath(f"{self.dataset.key}.ndjson"), "r") as result_file:
                for line in result_file:
                    if self.interrupted:
                        raise ProcessorInterruptedException("Interrupted while writing results to file")
                    data = json.loads(line)
                    for filename, result_data in data.items():
                        # should be one file per line
                        data = {
                            "id": filename,
                            "text": result_data.pop("text"),
                            **result_data,
                            "image_metadata": image_metadata.get(".".join(filename.split(".")[:-1]), {}) if image_metadata else {},
                        }
                        outfile.write(json.dumps(data) + "\n")
                        processed += 1

        self.dataset.update_status(f"Generated captions/responses in {processed} of {total_image_files} images")
        self.dataset.finish(processed)

    @staticmethod
    def map_item(item):
        """
        :param item:
        :return:
        """
        image_metadata = item.get("image_metadata")
        return MappedItem({
            "id": item.get("id"),
            "text": item.get("text"),
            # "original_url": image_metadata.get("url", ""), # TODO: does not appear all image datasets are using URL properly...
            "image_filename": image_metadata.get("filename", ""),
            "post_ids": ", ".join([str(post_id) for post_id in image_metadata.get("post_ids", [])]),
            "from_dataset": image_metadata.get("from_dataset", ""),
        })
