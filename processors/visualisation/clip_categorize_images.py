"""
OpenAI CLIP categorize images
"""
import datetime
import os
import json
import time
import requests
from pathlib import Path
from json import JSONDecodeError


from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorException, ProcessorInterruptedException
from common.lib.user_input import UserInput
from common.config_manager import config

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
        "image-to-categories.clip_enabled": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Enable CLIP Image Categorization",
            "tooltip": "Must have access to DMI Service Manager server"
        },
        "image-to-categories.clip_num_files": {
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
        return config.get("image-to-categories.clip_enabled", False, user=user) and \
               config.get("dmi-service-manager.server_address", False, user=user) and \
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
        max_number_images = int(config.get("image-to-categories.clip_num_files", 100, user=user))
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

        local_or_remote = self.config.get("dmi-service-manager.local_or_remote")

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

        # Send Request
        if local_or_remote == "local":
            # DMI Service Manager has direct access to files
            api_endpoint = "clip_local"

            # Relative to PATH_DATA which should be where Docker mounts the container volume
            # TODO: path is just the staging_area name, but what if we move staging areas? DMI Service manager needs to know...
            mounted_staging_area = staging_area.absolute().relative_to(self.config.get("PATH_DATA").absolute())
            mounted_output_dir = output_dir.absolute().relative_to(self.config.get("PATH_DATA").absolute())

        elif local_or_remote == "remote":
            # Upload files
            api_endpoint = "clip_remote"

            texts_folder = f"texts_{self.dataset.key}"

            # Get labels to send server
            top_dataset = self.dataset.top_parent()
            folder_name = datetime.datetime.fromtimestamp(self.source_dataset.timestamp).strftime("%Y-%m-%d-%H%M%S") + '-' + \
                          ''.join(e if e.isalnum() else '_' for e in top_dataset.get_label()) + '-' + \
                          str(top_dataset.key)

            data = {'folder_name': folder_name}

            # Check if image files have already been sent
            self.dataset.update_status("Connecting to DMI Service Manager...")
            filename_url = self.config.get("dmi-service-manager.server_address").rstrip("/") + '/api/list_filenames?folder_name=' + folder_name
            filename_response = requests.get(filename_url, timeout=30)

            # Check if 4CAT has access to this PixPlot server
            if filename_response.status_code == 403:
                self.dataset.update_status("403: 4CAT does not have permission to use the DMI Service Manager server",
                                           is_final=True)
                self.dataset.finish(0)
                return

            uploaded_image_files = filename_response.json().get('images', [])
            if len(uploaded_image_files) > 0:
                self.dataset.update_status("Found %i image files previously uploaded" % (len(uploaded_image_files)))

            # Compare image files with previously uploaded
            to_upload_filenames = [filename for filename in image_filenames if filename not in uploaded_image_files]

            if len(to_upload_filenames) > 0 or texts_folder not in filename_response.json():
                # TODO: perhaps upload one at a time?
                api_upload_endpoint = self.config.get("dmi-service-manager.server_address").rstrip("/") + "/api/send_files"
                # TODO: don't create a silly empty file just to trick the service manager into creating a new folder
                with open(staging_area.joinpath("blank.txt"), 'w') as file:
                    file.write('')
                self.dataset.update_status(f"Uploading {len(to_upload_filenames)} image files")
                response = requests.post(api_upload_endpoint, files=[('images', open(staging_area.joinpath(file), 'rb')) for file in to_upload_filenames] + [(texts_folder, open(staging_area.joinpath("blank.txt"), 'rb'))], data=data, timeout=120)
                if response.status_code == 200:
                    self.dataset.update_status(f"Image files uploaded: {len(to_upload_filenames)}")
                else:
                    self.dataset.update_status(f"Unable to upload {len(to_upload_filenames)} files!")
                    self.log.error(f"DMI Service Manager upload error: {response.status_code} - {response.reason}")

            mounted_staging_area = Path(folder_name).joinpath("images")
            mounted_output_dir = Path(folder_name).joinpath(texts_folder)

        else:
            raise ProcessorException("dmi-service-manager.local_or_remote setting must be 'local' or 'remote'")

        # CLIP args
        data = {"args": ['--output_dir', f"data/{mounted_output_dir}",
                         "--model", model,
                         "--categories", f"{','.join(categories)}",
                         "--images"]
                }

        # Finally, add image files to args
        data["args"].extend([f"data/{mounted_staging_area.joinpath(filename)}" for filename in image_filenames])

        self.dataset.update_status(f"Requesting service from DMI Service Manager...")
        api_url = self.config.get("dmi-service-manager.server_address").rstrip("/") + "/api/" + api_endpoint
        resp = requests.post(api_url, json=data, timeout=30)
        if resp.status_code == 202:
            # New request successful
            results_url = api_url + "?key=" + resp.json()['key']
        else:
            try:
                resp_json = resp.json()
                self.log.error('DMI Service Manager error: ' + str(resp.status_code) + ': ' + str(resp_json))
                raise ProcessorException("DMI Service Manager unable to process request; contact admins")
            except JSONDecodeError:
                # Unexpected Error
                self.log.error('DMI Service Manager error: ' + str(resp.status_code) + ': ' + str(resp.text))
                raise ProcessorException("DMI Service Manager unable to process request; contact admins")

        # Wait for CLIP to complete
        self.dataset.update_status(f"CLIP generating results for {total_image_files} images{'; this may take quite a while...' if total_image_files > 1000 else ''}")
        start_time = time.time()
        prev_completed = 0
        while True:
            time.sleep(1)
            # If interrupted is called, attempt to finish dataset while CLIP server still running (unsure how to kill it; need new DMI Service Manager API endpoint)
            if self.interrupted:
                self.dataset.update_status("4CAT interrupted; Processing successful CLIP results...",
                                           is_final=True)
                break

            # Send request to check status every 10 seconds; with GPU, CLIP should be able to process smaller (<200 images) datasets in 10 seconds
            if int(time.time() - start_time) % 10 == 0:
                # Update progress
                if local_or_remote == "local":
                    num_completed = self.count_result_files(output_dir)
                    if num_completed != prev_completed:
                        self.dataset.update_status(f"Collected categories from {num_completed} of {total_image_files} images")
                        self.dataset.update_progress(num_completed / total_image_files)
                        prev_completed = num_completed
                elif local_or_remote == "remote":
                    # TODO could check API endpoint if desired...
                    num_completed = 1 # in case.... yeah, unsure yet, but do not want to kill a dataset that may have results
                    pass

                result = requests.get(results_url, timeout=30)
                if 'status' in result.json().keys() and result.json()['status'] == 'running':
                    # Still running
                    continue
                elif 'report' in result.json().keys() and result.json()['returncode'] == 0:
                    # Complete without error
                    self.dataset.update_status("CLIP Completed!")
                    break
                else:
                    # Something botched
                    if num_completed > 0:
                        # Some data collected...
                        self.dataset.update_status("CLIP Error; check logs; Processing successful CLIP results...", is_final=True)
                        error_message = f"CLIP Error (dataset {self.dataset.key}): {str(result.json())}"
                        self.log.error(error_message)
                        self.dataset.log(error_message)
                        break
                    else:
                        self.dataset.finish_with_error("CLIP Error; unable to process request")
                        self.log.error("CLIP Error: " + str(result.json()))
                        return

        # Load the video metadata if available
        image_metadata = None
        if staging_area.joinpath(".metadata.json").is_file():
            with open(staging_area.joinpath(".metadata.json")) as file:
                image_metadata = json.load(file)
                self.dataset.log("Found and loaded image metadata")

        self.dataset.update_status("Processing CLIP results...")
        if local_or_remote == "local":
            # Output files are local
            pass
        elif local_or_remote == "remote":
            # Update list of uploaded files
            filename_response = requests.get(filename_url, timeout=30)
            result_files = filename_response.json().get(texts_folder, [])

            # Download the result files
            api_upload_endpoint = self.config.get("dmi-service-manager.server_address").rstrip("/") + "/api/uploads/"
            for filename in result_files:
                file_response = requests.get(api_upload_endpoint + f"{folder_name}/{texts_folder}/{filename}", timeout=30)
                self.dataset.log(f"Downloading {filename}...")
                with open(output_dir.joinpath(filename), 'wb') as file:
                    file.write(file_response.content)
        else:
            # This should have raised already...
            raise ProcessorException("dmi-service-manager.local_or_remote setting must be 'local' or 'remote'")

        # Save files as NDJSON, then use map_item for 4CAT to interact
        processed = 0
        with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile:
            for result_filename in os.listdir(output_dir):
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while writing results to file")

                self.dataset.log(f"Writing {result_filename}...")
                with open(output_dir.joinpath(result_filename), "r") as result_file:
                    result_data = json.loads(''.join(result_file))
                    image_name = ".".join(result_filename.split(".")[:-1])
                    data = {
                        "id": image_name,
                        "categories": result_data,
                        # TODO: need to pass along filename/videoname/postid/SOMETHING consistent
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
        return {
            "id": item.get("id"),
            "top_categories": ", ".join([f"{cat[0]}: {100* cat[1]:.2f}%" for cat in top_cats]),
            "original_url": image_metadata.get("url", ""),
            "image_filename": image_metadata.get("filename", ""),
            "post_ids": ", ".join(image_metadata.get("post_ids", [])),
            "from_dataset": image_metadata.get("from_dataset", ""),
            **all_cats
        }

    @staticmethod
    def count_result_files(directory):
        """
        Get number of files in directory
        """
        return len(os.listdir(directory))
