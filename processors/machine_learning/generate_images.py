"""
Generate images with Stable Diffusion

Why? Because we can.
"""
import shutil
import json
import re

from backend.lib.processor import BasicProcessor
from processors.visualisation.download_images import ImageDownloader
from common.lib.dmi_service_manager import DmiServiceManager, DmiServiceManagerException, DsmOutOfMemory
from common.lib.user_input import UserInput

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class StableDiffusionImageGenerator(BasicProcessor):
    """
    Generate images with Stable Diffusion
    """
    type = "image-downloader-stable-diffusion"  # job type ID
    category = "Visual"  # category
    title = "Generate images from text prompts"  # title displayed in UI
    description = "Given a list of prompts, generates images using the Stable Diffusion XL image model."  # description displayed in UI
    extension = "zip"  # extension of result file, used internally and in UI

    followups = ImageDownloader.followups

    references = [
        "[Stable Diffusion XL 1.0 model card](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0)"
    ]

    config = {
        "dmi-service-manager.sd_intro-1": {
            "type": UserInput.OPTION_INFO,
            "help": "StabilityAI's Stable Diffusion model can generate images for a given text prompt. Ensure the DMI "
                    "Service Manager is running and has a [prebuilt SD XL "
                    "image](https://github.com/digitalmethodsinitiative/dmi_dockerized_services/tree/main/stable_diffusion).",
        },
        "dmi-service-manager.sd_enabled": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Enable Stable Diffusion image generation",
        },
        "dmi-service-manager.sd_num_files": {
            "type": UserInput.OPTION_TEXT,
            "coerce_type": int,
            "default": 0,
            "help": "Max images to generate with Stable Diffusion",
            "tooltip": "Use '0' to allow unlimited number"
        },
    }

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
        """
        Get processor options

        These are dynamic for this processor: the 'column names' option is
        populated with the column names from the parent dataset, if available.

        :param config:
        :param DataSet parent_dataset:  Parent dataset
        :return dict:  Processor options
        """
        options = {
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "coerce_type": int,
                "help": "Number of images to generate",
                "default": 20,
            },
            "prompt-column": {
                "type": UserInput.OPTION_TEXT,
                "default": False,
                "help": "Dataset field containing prompt",
                "tooltip": "Prompts will be truncated to 70 characters"
            },
            "negative-prompt-column": {
                "type": UserInput.OPTION_TEXT,
                "default": False,
                "help": "Dataset field containing negative prompt",
                "tooltip": "The model will try to avoid generating an image that fits the negative prompt. Prompts will be "
                        "truncated to 70 characters"
            }
        }
        if parent_dataset is None:
            return options

        parent_columns = parent_dataset.get_columns()

        if parent_columns:
            parent_columns = {c: c for c in sorted(parent_columns)}
            options["prompt-column"].update({
                "type": UserInput.OPTION_CHOICE,
                "options": parent_columns,
            })

            # negative prompt optional, so add empty option
            options["negative-prompt-column"].update({
                "type": UserInput.OPTION_CHOICE,
                "options": {"": "", **parent_columns},
                "default": ""
            })
        max_prompts = config.get("dmi-service-manager.sd_num_files", 0)
        if max_prompts == 0:
            options["amount"]["tooltip"] = "Use '0' to allow unlimited number"
        else:
            options["amount"]["help"] = f"Number of images to generate (max {max_prompts})"
            options["amount"]["min"] = 1
            options["amount"]["max"] = max_prompts
            options["amount"]["default"] = min(max_prompts, 20)

        return options

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Allow on datasets with columns (from which a prompt can be retrieved)
        """
        return config.get("dmi-service-manager.sd_enabled", False) and \
            config.get("dmi-service-manager.ab_server_address", False) and \
            module.get_columns()

    @staticmethod
    def get_progress_callback(num_prompts):
        """
        Callback for updating dataset progress

        This generates a function that is periodically called by the service
        manager to update the progress of the query. It sets the progress and
        updates the dataset status.

        :param int num_prompts:  Total number of prompts that will be processed.
        :return: Callback
        """

        def callback(manager):
            if manager.local_or_remote == "local":
                current_completed = manager.count_local_files(
                    manager.processor.config.get("PATH_DATA").joinpath(manager.path_to_results))
            elif manager.local_or_remote == "remote":
                existing_files = manager.request_folder_files(manager.server_file_collection_name)
                current_completed = len(existing_files.get(manager.server_results_folder_name, []))

            manager.processor.dataset.update_status(
                f"Generated images for {current_completed:,} of {num_prompts:,} prompt(s)")
            manager.processor.dataset.update_progress(current_completed / num_prompts)

        return callback

    def process(self):
        """
        This takes a dataset and generates images for prompts retrieved from that dataset
        """
        prompts = {}
        hard_max_prompts = self.config.get("dmi-service-manager.sd_num_files")
        user_max_prompts = self.parameters.get("amount", 20)

        prompt_c = self.parameters["prompt-column"]
        neg_c = self.parameters.get("negative-prompt-column")
        for item in self.source_dataset.iterate_items(self):
            if hard_max_prompts != 0 and len(prompts) >= hard_max_prompts:
                break
            elif user_max_prompts != 0 and len(prompts) >= user_max_prompts:
                break

            prompts[item.get("id", len(prompts) + 1)] = {
                "prompt": item.get(prompt_c, ""),
                "negative": item.get(neg_c) if item.get(neg_c) is not None else ""
            }

        if not any([p["prompt"] for p in prompts.values()]):
            return self.dataset.finish_with_error(
                f"No prompts found in dataset's '{prompt_c}' field. Use a different field and try again.")

        # Make output dir
        staging_area = self.dataset.get_staging_area()
        output_dir = self.dataset.get_staging_area()

        # Initialize DMI Service Manager
        dmi_service_manager = DmiServiceManager(processor=self)

        # Check GPU memory available
        try:
            gpu_response = dmi_service_manager.check_gpu_memory_available("stable_diffusion")
        except DmiServiceManagerException as e:
            if "GPU not enabled on this instance of DMI Service Manager" in str(e):
                self.dataset.update_status(
                    "GPU not enabled on this instance of DMI Service Manager; this may be a minute...")
                gpu_response = None
            else:
                return self.dataset.finish_with_error(str(e))

        if gpu_response and int(gpu_response.get("memory", {}).get("gpu_free_mem", 0)) < 1000000:
            self.dataset.finish_with_error(
                "DMI Service Manager currently busy; no GPU memory available. Please try again later.")
            return

        # Results should be unique to this dataset
        results_folder_name = f"images_{self.dataset.key}"
        file_collection_name = dmi_service_manager.get_folder_name(self.dataset)

        # the prompts may be lengthy, so dump them in a file rather than
        # relying on passing them as a command line argument
        prompts_file = staging_area.joinpath("prompts.temp.json")
        with prompts_file.open("w") as outfile:
            json.dump(prompts, outfile)

        path_to_files, path_to_results = dmi_service_manager.process_files(staging_area, [prompts_file.name],
                                                                           output_dir, file_collection_name,
                                                                           results_folder_name)

        # interface.py args
        data = {"timeout": (86400 * 7), "args": ['--output-dir', f"data/{path_to_results}",
                                                 "--prompts-file",
                                                 f"data/{path_to_files.joinpath(dmi_service_manager.sanitize_filenames(prompts_file.name))}"],
                "pass_key": True,  # This tells the DMI SM there is a status update endpoint in the clip image

                }

        # Send request to DMI Service Manager
        self.dataset.update_status("Requesting service from DMI Service Manager...")
        api_endpoint = "stable_diffusion"

        try:
            dmi_service_manager.send_request_and_wait_for_results(api_endpoint, data, wait_period=5, check_process=None,
                                                                  callback=self.get_progress_callback(len(prompts)))
        except DsmOutOfMemory:
            shutil.rmtree(staging_area)
            shutil.rmtree(output_dir)
            return self.dataset.finish_with_error(
                "DMI Service Manager ran out of memory; Try decreasing the number of prompts or try again or try again later.")
        except DmiServiceManagerException as e:
            shutil.rmtree(staging_area)
            shutil.rmtree(output_dir)
            return self.dataset.finish_with_error(str(e))

        # Download the result files
        self.dataset.update_status("Processing generated images...")
        dmi_service_manager.process_results(output_dir)

        # Output folder is basically already ready for archiving
        # Add a metadata JSON file before that though
        def make_filename(id, prompt):
            """
            Generate filename for generated image

            Should mirror the make_filename method in interface.py in the SD Docker.

            :param prompt_id:  Unique identifier, eg `54`
            :param str prompt:  Text prompt, will be sanitised, e.g. `Rasta Bill Gates`
            :return str:  For example, `54-rasta-bill-gates.jpeg`
            """
            safe_prompt = re.sub(r"[^a-zA-Z0-9 _-]", "", prompt).replace(" ", "-").lower()[:90]
            return f"{id}-{safe_prompt}.jpeg"

        self.dataset.update_status("Verifying results")
        with output_dir.joinpath(".metadata.json").open("w") as outfile:
            metadata = {
                prompt_id: {
                    "from_dataset": self.source_dataset.key,
                    "filename": make_filename(prompt_id, data["prompt"]),
                    "success": output_dir.joinpath(make_filename(prompt_id, data["prompt"])).exists(),
                    "post_ids": [prompt_id],
                    "prompt": data["prompt"],
                    "negative-prompt": data["negative"],
                } for prompt_id, data in prompts.items()
            }
            json.dump(metadata, outfile)

        shutil.rmtree(staging_area)

        self.dataset.update_status(
            f"Generated {len([r for r in metadata.values() if r['success']]):,} image(s) for {len(prompts):,} prompt(s)",
            is_final=True)
        self.write_archive_and_finish(output_dir, num_items=len([r for r in metadata.values() if r['success']]))
