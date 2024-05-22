"""
Whisper convert speech in audio to text
"""
import os
import json

from backend.lib.processor import BasicProcessor
from common.lib.dmi_service_manager import DmiServiceManager, DmiServiceManagerException, DsmOutOfMemory, \
    DsmConnectionError
from common.lib.exceptions import ProcessorException, ProcessorInterruptedException
from common.lib.user_input import UserInput
from common.config_manager import config
from common.lib.item_mapping import MappedItem

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class AudioToText(BasicProcessor):
    """
    Convert audio to text with Whisper
    """
    type = "audio-to-text"  # job type ID
    category = "Audio"  # category
    title = "Whisper: Convert speech to text"  # title displayed in UI
    description = "Detect speech in audion and convert to text."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI

    references = [
        "[OpenAI Whisper blog](https://openai.com/research/whisper)",
        "[Whisper paper: Robust Speech Recognition via Large-Scale Weak Supervision](https://arxiv.org/abs/2212.04356)",
        "[OpenAI Whisper statistics & code](https://github.com/openai/whisper#whisper)",
        "[How to use prompts](https://platform.openai.com/docs/guides/speech-to-text/prompting)",
        ]

    config = {
        "dmi-service-manager.bb_whisper-intro-1": {
            "type": UserInput.OPTION_INFO,
            "help": "Whisper converts speech in audio to text. Ensure the DMI Service Manager is running and has a [prebuilt Whisper image](https://github.com/digitalmethodsinitiative/dmi_dockerized_services/tree/main/openai_whisper#dmi-implementation-of-whisper-audio-transcription-tool).",
        },
        "dmi-service-manager.bc_whisper_enabled": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Enable Whisper Speech to Text",
        },
        "dmi-service-manager.bd_whisper_num_files": {
            "type": UserInput.OPTION_TEXT,
            "coerce_type": int,
            "default": 0,
            "help": "Whisper max number of audio files",
            "tooltip": "Use '0' to allow unlimited number"
        }
    }

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow on audio archives if enabled in Control Panel
        """
        return config.get("dmi-service-manager.bc_whisper_enabled", False, user=user) and \
               config.get("dmi-service-manager.ab_server_address", False, user=user) and \
               module.type.startswith("audio-extractor")

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        Collect maximum number of audio files from configuration and update options accordingly
        """
        options = {
            "amount": {
                "type": UserInput.OPTION_TEXT
            },
            # Whisper model options
            # TODO: Could limit model availability in conjunction with "amount"
            "model": {
                "type": UserInput.OPTION_CHOICE,
                "help": f"Whisper model",
                "default": "base",
                "tooltip": "Larger sizes increase quality at expense of greatly increasing the amount of time to process. Try the Base model and increase as needed.",
                "options": {
                    "tiny.en": "Tiny English",
                    "tiny": "Tiny Detect Language",
                    "base.en": "Base English",
                    "base": "Base Detect Language",
                    "small.en": "Small English",
                    "small": "Small Detect Language",
                    "medium.en": "Medium English",
                    "medium": "Medium Detect Language",
                    "large": "Large Detect Language"
                }
            },
            "prompt": {
                "type": UserInput.OPTION_TEXT,
                "help": "Prompt model (see references)",
                "default": "",
                "tooltip": "Prompts can aid the model in specific vocabulary detection, to add punctuation or filler words."
            },
            "translate": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Translate transcriptions to English",
                "default": False,
                "tooltip": "Original language still listed in \"language\" column"
            },
            "advanced": {
                "type": UserInput.OPTION_TEXT_JSON,
                "help": "[Advanced settings](https://github.com/openai/whisper/blob/248b6cb124225dd263bb9bd32d060b6517e067f8/whisper/transcribe.py#LL374C3-L374C3)",
                "default": {},
                "tooltip": "Additional settings can be provided as a JSON e.g., {\"--no_speech_threshold\": 0.2, \"--logprob_threshold\": -0.5}."
            }
        }

        # Update the amount max and help from config
        max_number_audio_files = int(config.get("dmi-service-manager.bd_whisper_num_files", 100, user=user))
        if max_number_audio_files == 0:  # Unlimited allowed
            options["amount"]["help"] = "Number of audio files"
            options["amount"]["default"] = 100
            options["amount"]["min"] = 0
            options["amount"]["tooltip"] = "Use '0' to convert all audio (this can take a very long time)"
        else:
            options["amount"]["help"] = f"Number of audio files (max {max_number_audio_files})"
            options["amount"]["default"] = min(max_number_audio_files, 100)
            options["amount"]["max"] = max_number_audio_files
            options["amount"]["min"] = 1

        return options

    def process(self):
        """
        This takes a zipped set of audio files and uses a Whisper docker image to identify speech and convert to text.
        """
        audio_files_extracted = 0
        if self.source_dataset.num_rows <= 1:
            # 1 because there is always a metadata file
            self.dataset.finish_with_error("No audio files found.")
            return

        # Check advanced_settings
        advanced_settings = self.parameters.get("advanced", False)
        if advanced_settings:
            try:
                advanced_settings = json.loads(advanced_settings)
            except ValueError:
                self.dataset.finish_with_error("Unable to parse Advanced settings. Please format as JSON.")
                return

        # Unpack the audio files into a staging_area
        self.dataset.update_status("Unzipping audio files")
        staging_area = self.unpack_archive_contents(self.source_file)
        # Prepare output dir
        output_dir = self.dataset.get_staging_area()

        # Collect filenames (skip .json metadata files)
        audio_filenames = [filename for filename in os.listdir(staging_area) if filename.split('.')[-1] not in ["json", "log"]]
        if self.parameters.get("amount", 100) != 0:
            audio_filenames = audio_filenames[:self.parameters.get("amount", 100)]
        total_audio_files = len(audio_filenames)

        # Initialize DMI Service Manager
        dmi_service_manager = DmiServiceManager(processor=self)

        # Check connection and GPU memory available
        try:
            gpu_response = dmi_service_manager.check_gpu_memory_available("whisper")
        except DmiServiceManagerException as e:
            return self.dataset.finish_with_error(str(e))

        if int(gpu_response.get("memory", {}).get("gpu_free_mem", 0)) < 1000000:
            self.dataset.finish_with_error("DMI Service Manager currently busy; no GPU memory available. Please try again later.")
            return

        # Provide audio files to DMI Service Manager
        # Results should be unique to this dataset
        results_folder_name = f"texts_{self.dataset.key}"
        # Files can be based on the parent dataset (to avoid uploading the same files multiple times)
        file_collection_name = dmi_service_manager.get_folder_name(self.source_dataset)

        path_to_files, path_to_results = dmi_service_manager.process_files(staging_area, audio_filenames, output_dir, file_collection_name, results_folder_name)

        # Whisper args
        whisper_endpoint = "whisper"
        data = {"args": ['--output_dir', f"data/{path_to_results}",
                         "--verbose", "False",
                         '--output_format', "json",
                         "--model", self.parameters.get("model")],
                }
        prompt = self.parameters.get("prompt", "")
        if prompt:
            data["args"].extend(["--initial_prompt", prompt])
        translate = self.parameters.get("translate", False)
        if translate:
            data["args"].extend(["--task", 'translate'])
        if advanced_settings:
            for setting, value in advanced_settings.items():
                setting = setting if setting[:2] == "--" else "--" + setting.lstrip("-")
                data["args"].extend([setting, str(value)])
        # Finally, add audio files to args
        data["args"].extend([f"data/{path_to_files.joinpath(dmi_service_manager.sanitize_filenames(filename))}" for filename in audio_filenames])

        # Send request to DMI Service Manager
        self.dataset.update_status(f"Requesting service from DMI Service Manager...")
        try:
            dmi_service_manager.send_request_and_wait_for_results(whisper_endpoint, data, wait_period=30)
        except DsmOutOfMemory:
            self.dataset.finish_with_error(
                "DMI Service Manager ran out of memory; Try decreasing the number of audio files or try again or try again later.")
            return
        except DmiServiceManagerException as e:
            self.dataset.finish_with_error(str(e))
            return

        # Load the video metadata if available
        video_metadata = None
        if staging_area.joinpath(".video_metadata.json").is_file():
            with open(staging_area.joinpath(".video_metadata.json")) as file:
                video_metadata = json.load(file)
                self.dataset.log("Found and loaded video metadata")

        self.dataset.update_status("Processing Whisper results...")

        # Download the result files
        dmi_service_manager.process_results(output_dir)

        # Save files as NDJSON, then use map_item for 4CAT to interact
        processed = 0
        with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile:
            for result_filename in os.listdir(output_dir):
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while writing results to file")

                self.dataset.log(f"Writing {result_filename}...")
                with open(output_dir.joinpath(result_filename), "r") as result_file:
                    result_data = json.loads(''.join(result_file))
                    audio_name = ".".join(result_filename.split(".")[:-1])
                    fourcat_metadata = {
                        "audio_id": audio_name,
                        # TODO: need to pass along filename/videoname/postid/SOMETHING consistent
                        "audio_metadata": video_metadata.get(audio_name, {}) if video_metadata else {},
                    }
                    result_data.update({"4CAT_metadata": fourcat_metadata})
                    outfile.write(json.dumps(result_data) + "\n")

                    processed += 1

        self.dataset.update_status(f"Detected speech in {processed} of {total_audio_files} audio files")
        self.dataset.finish(processed)
            
    @staticmethod
    def map_item(item):
        """
        :param item:
        :return:
        """
        fourcat_metadata = item.get("4CAT_metadata")
        audio_metadata = fourcat_metadata.get("audio_metadata")
        return MappedItem({
            "id": fourcat_metadata.get("audio_id"),
            "body": item.get("text", ""),
            "language": item.get("language", ""),
            "segments": ",\n".join(
                [f"text: {segment['text']} (start: {segment['start']}; end: {segment['end']}; )" for segment in
                 item.get("segments", [])]),
            "original_video_url": audio_metadata.get("url", ""),
            "post_ids": ", ".join(audio_metadata.get("post_ids", [])),
            "from_dataset": audio_metadata.get("from_dataset", "")
        })
