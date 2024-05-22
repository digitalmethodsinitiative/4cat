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
    Categorize Images with OpenAI CLIP
    """
    type = "image-to-categories"  # job type ID
    category = "Visual"  # category
    title = "Categorize Images using OpenAI's CLIP models"  # title displayed in UI
    description = "Given a list of categories, the CLIP model will estimate likelihood an image is to belong to each (total of all categories per image will be 100%)."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI

    references = [
        "[OpenAI CLIP blog](https://openai.com/research/clip)",
        "[CLIP paper: Learning Transferable Visual Models From Natural Language Supervision](https://arxiv.org/pdf/2103.00020.pdf)",
        "[OpenAI CLIP code](https://github.com/openai/CLIP/#clip)",
        "[Model comparison](https://arxiv.org/pdf/2103.00020.pdf#page=40&zoom=auto,-457,754)",
        ]

    config = {
        "dmi-service-manager.cb_clip-intro-1": {
            "type": UserInput.OPTION_INFO,
            "help": "OpenAI's CLIP model estimates the probability an image belongs to each of a list of user defined categories. Ensure the DMI Service Manager is running and has a [prebuilt CLIP image](https://github.com/digitalmethodsinitiative/dmi_dockerized_services/tree/main/openai_clip#dmi-implementation-of-openai-clip-image-categorization-tool).",
        },
        "dmi-service-manager.cc_clip_enabled": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Enable CLIP Image Categorization",
        },
        "dmi-service-manager.cd_clip_num_files": {
            "type": UserInput.OPTION_TEXT,
            "coerce_type": int,
            "default": 0,
            "help": "CLIP max number of images",
            "tooltip": "Use '0' to allow unlimited number"
        },
    }

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow on image archives if enabled in Control Panel
        """
        return config.get("dmi-service-manager.cc_clip_enabled", False, user=user) and \
               config.get("dmi-service-manager.ab_server_address", False, user=user) and \
               module.type.startswith("image-downloader")

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        Collect maximum number of files from configuration and update options accordingly
        """
        options = {
            "amount": {
                "type": UserInput.OPTION_TEXT
            },
            # CLIP model options
            # TODO: Could limit model availability in conjunction with "amount"
            "model": {
                "type": UserInput.OPTION_CHOICE,
                "help": f"[CLIP model](https://arxiv.org/pdf/2103.00020.pdf#page=40&zoom=auto,-457,754)",
                "default": "ViT-B/32",
                "tooltip": "More powerful models increase quality at expense of greatly increasing the amount of time to process. Recommend testing small amounts of images first.",
                "options": {
                    "RN50": "RN50",
                    "RN101": "RN101",
                    "RN50x4": "RN50x4",
                    "RN50x16": "RN50x16",
                    "ViT-B/32": "ViT-B/32",
                    "ViT-B/16": "ViT-B/16",
                    "ViT-L/14": "ViT-L/14",
                    "ViT-L/14@336px": "ViT-L/14@336px",
                }
            },
            "categories": {
                "type": UserInput.OPTION_TEXT,
                "help": "Categories (comma seperated list)",
                "default": "",
                "tooltip": "The CLIP model will estimate the probability an image belongs to every category, adding up to 100% across categories. It is quite robust and can accept proper nouns, some celebrities, as well as understand syntax such as \"animal\" vs \"not animal\""
            },
        }

        # Update the amount max and help from config
        max_number_images = int(config.get("dmi-service-manager.cd_clip_num_files", 100, user=user))
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
        categories = [cat.strip() for cat in self.parameters.get('categories').split(',')]
        model = self.parameters.get("model")
        if self.source_dataset.num_rows <= 1:
            # 1 because there is always a metadata file
            self.dataset.finish_with_error("No images found.")
            return
        elif not categories:
            self.dataset.finish_with_error("No categories provided.")
            return
        elif not model:
            self.dataset.finish_with_error("No model provided.")
            return

        # Unpack the image files into a staging_area
        self.dataset.update_status("Unzipping image files")
        staging_area = self.unpack_archive_contents(self.source_file)

        # Collect filenames (skip .json metadata files)
        image_filenames = [filename for filename in os.listdir(staging_area) if filename.split('.')[-1] not in ["json", "log"]]
        if self.parameters.get("amount", 100) != 0:
            image_filenames = image_filenames[:self.parameters.get("amount", 100)]
        total_image_files = len(image_filenames)

        # Make output dir
        output_dir = self.dataset.get_staging_area()

        # Initialize DMI Service Manager
        dmi_service_manager = DmiServiceManager(processor=self)

        # Check connection, ser and GPU memory available
        try:
            gpu_response = dmi_service_manager.check_gpu_memory_available("clip")
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

        # CLIP args
        data = {"args": ['--output_dir', f"data/{path_to_results}",
                         "--model", model,
                         "--categories", f"{','.join(categories)}",
                         "--images"]
                }

        # Finally, add image files to args
        data["args"].extend([f"data/{path_to_files.joinpath(dmi_service_manager.sanitize_filenames(filename))}" for filename in image_filenames])

        # Send request to DMI Service Manager
        self.dataset.update_status(f"Requesting service from DMI Service Manager...")
        api_endpoint = "clip"
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
        if staging_area.joinpath(".metadata.json").is_file():
            with open(staging_area.joinpath(".metadata.json")) as file:
                image_data = json.load(file)
                self.dataset.log("Found and loaded image metadata")
                for url, data in image_data.items():
                    if data.get('success'):
                        data.update({"url": url})
                        # using the filename without extension as the key; since that is how the results form their filename
                        image_metadata[".".join(data['filename'].split(".")[:-1])] = data

        self.dataset.update_status("Processing CLIP results...")
        # Download the result files
        dmi_service_manager.process_results(output_dir)

        # Save files as NDJSON, then use map_item for 4CAT to interact
        processed = 0
        with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile:
            for result_filename in os.listdir(output_dir):
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while writing results to file")

                with open(output_dir.joinpath(result_filename), "r") as result_file:
                    if not result_filename.endswith(".json"):
                        self.dataset.log(f"Skipping {result_filename} (not a JSON results file)")
                        continue
                    result_data = json.loads(''.join(result_file))
                    image_name = ".".join(result_filename.split(".")[:-1])
                    data = {
                        "id": image_name,
                        "categories": result_data,
                        "image_metadata": image_metadata.get(image_name, {}) if image_metadata else {},
                    }
                    outfile.write(json.dumps(data) + "\n")

                    processed += 1

        self.dataset.update_status(f"Detected speech in {processed} of {total_image_files} images")
        self.dataset.finish(processed)

    @staticmethod
    def map_item(item):
        """
        :param item:
        :return:
        """
        image_metadata = item.get("image_metadata")
        top_cats = []
        percent = 0
        for cat in item.get("categories", []):
            if percent > .7:
                break
            top_cats.append(cat)
            percent += cat[1]
        all_cats = {cat[0]: cat[1] for cat in item.get("categories", [])}
        return MappedItem({
            "id": item.get("id"),
            "top_categories": ", ".join([f"{cat[0]}: {100* cat[1]:.2f}%" for cat in top_cats]),
            "original_url": image_metadata.get("url", ""),
            "image_filename": image_metadata.get("filename", ""),
            "post_ids": ", ".join([str(post_id) for post_id in image_metadata.get("post_ids", [])]),
            "from_dataset": image_metadata.get("from_dataset", ""),
            **all_cats
        })

    @staticmethod
    def count_result_files(directory):
        """
        Get number of files in directory
        """
        return len(os.listdir(directory))
