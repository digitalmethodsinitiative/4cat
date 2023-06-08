"""
Whisper convert speech in audio to text
"""
import os
import json
import time
import requests
from json import JSONDecodeError


from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorException
from common.lib.user_input import UserInput
import common.config_manager as config

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
    title = "Convert speech to text"  # title displayed in UI
    description = "Detect speech in audion and convert to text."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    config = {
        "dmi_service_manager.server_address": {
            "type": UserInput.OPTION_TEXT,
            "default": "",
            "help": "DMI Service Manager server/URL",
            "tooltip": "https://github.com/digitalmethodsinitiative/dmi_service_manager"
        },
        "dmi_service_manager.local_or_remote": {
            "type": UserInput.OPTION_CHOICE,
            "default": 0,
            "help": "DMI Services Local or Remote",
            "tooltip": "Services have local access to 4CAT files or must be transferred from remote via DMI Service Manager",
            "options": {
                "local": "Local",
                "remote": "Remote",
            },
        },
        "dmi_service_manager.whisper_enabled": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Enable Whisper Speech to Text",
            "tooltip": "Docker must be installed and the Whisper image downloaded/built."
        },
        "dmi_service_manager.whisper_num_files": {
            "type": UserInput.OPTION_TEXT,
            "coerce_type": int,
            "default": 0,
            "help": "Whisper max number of audio files",
            "tooltip": "Use '0' to allow unlimited number"
        },
    }

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Allow on audio archives if enabled in Control Panel
        """
        return config.get("dmi_service_manager.whisper_enabled", False) and \
               config.get("dmi_service_manager.server_address", False) and \
               module.type.startswith("audio-extractor")

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        Collect maximum number of audio files from configuration and update options accordingly
        """
        options = cls.options if hasattr(cls, "options") else {}

        # Update the amount max and help from config
        max_number_audio_files = int(config.get("dmi_service_manager.whisper_num_files", 100))
        if max_number_audio_files == 0:  # Unlimited allowed
            options["amount"] = {
                "type": UserInput.OPTION_TEXT,
                "help": "Number of audio files",
                "default": 100,
                "min": 0,
                "tooltip": "Use '0' to convert all audio (this can take a very long time)"
            }
        else:
            options["amount"] = {
                "type": UserInput.OPTION_TEXT,
                "help": f"Number of audio files (max {max_number_audio_files})",
                "default": min(max_number_audio_files, 100),
                "max": max_number_audio_files,
                "min": 1,
            }

        # Whisper model options
        # TODO: Could limit model availability in conjunction with "amount"
        options["model"] = {
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
            },
        }

        return options

    def process(self):
        """
        This takes a zipped set of audio files and uses a Whisper docker image to identify speech and convert to text.
        """
        if self.source_dataset.num_rows <= 1:
            # 1 because there is always a metadata file
            self.dataset.finish_with_error("No audio files found.")
            return

        # Unpack the audio files into a staging_area
        self.dataset.update_status("Unzipping audio files")
        staging_area = self.unpack_archive_contents(self.source_file)
        # Relative to PATH_DATA which should be where Docker mounts the whisper container volume
        # TODO: shore this up
        mounted_staging_area = staging_area.absolute().relative_to(config.get("PATH_DATA").absolute())

        # Collect filenames (skip .json metadata files)
        audio_filenames = [filename for filename in os.listdir(staging_area) if filename.split('.')[-1] not in ["json", "log"]]
        if self.parameters.get("amount", 100) != 0:
            audio_filenames = audio_filenames[:self.parameters.get("amount", 100)]
        total_audio_files = len(audio_filenames)

        # Make output dir
        output_dir = self.dataset.get_staging_area()
        # Relative to PATH_DATA which should be where Docker mounts the whisper container volume
        # TODO: shore this up
        mounted_output_dir = output_dir.absolute().relative_to(config.get("PATH_DATA").absolute())

        # Whisper args
        data = {"args": ['--output_dir', f"data/{mounted_output_dir}",
                         "--verbose", "False",
                         '--output_format', "json",
                         "--model", self.parameters.get("model")] +
                        [f"data/{mounted_staging_area.joinpath(filename)}" for filename in audio_filenames]
                }

        # Send Request
        whisper_endpoint = "whisper"
        api_endpoint = config.get("dmi_service_manager.server_address").rstrip("/") + "/api/" + whisper_endpoint
        resp = requests.post(api_endpoint, json=data, timeout=30)
        if resp.status_code == 202:
            # New request successful
            results_url = api_endpoint + "?key=" + resp.json()['key']
        else:
            try:
                resp_json = resp.json()
                self.log.error('DMI Service Manager error: ' + str(resp.status_code) + ': ' + str(resp_json))
                raise ProcessorException("DMI Service Manager unable to process request; contact admins")
            except JSONDecodeError:
                # Unexpected Error
                self.log.error('DMI Service Manager error: ' + str(resp.status_code) + ': ' + str(resp.text))
                raise ProcessorException("DMI Service Manager unable to process request; contact admins")

        # Wait for Whisper to convert audio to text
        self.dataset.update_status(f"Whisper generating results for {total_audio_files} audio files{'; this may take quite a while...' if total_audio_files > 25 else ''}")
        start_time = time.time()
        prev_completed = 0
        while True:
            time.sleep(1)
            # If interrupted is called, attempt to finish dataset while Whisper server still running
            if self.interrupted:
                self.dataset.update_status("4CAT interrupted; Processing successful Whisper results...",
                                           is_final=True)
                break

            # Send request to check status every 60 seconds
            if int(time.time() - start_time) % 60 == 0:
                # Update progress
                num_completed = self.count_result_files(output_dir)
                if num_completed != prev_completed:
                    self.dataset.update_status(f"Collected text from {num_completed} of {total_audio_files} audio files")
                    self.dataset.update_progress(num_completed / total_audio_files)
                    prev_completed = num_completed

                result = requests.get(results_url, timeout=30)
                if 'status' in result.json().keys() and result.json()['status'] == 'running':
                    # Still running
                    continue
                elif 'report' in result.json().keys() and result.json()['returncode'] == 0:
                    # Complete without error
                    self.dataset.update_status("Whisper Completed!")
                    break
                else:
                    # Something botched
                    if num_completed > 0:
                        # Some data collected...
                        self.dataset.update_status("Whisper Error; check logs; Processing successful Whisper results...", is_final=True)
                        error_message = "Whisper Error: " + str(result.json())
                        self.log.error(error_message)
                        self.dataset.log(error_message)
                        break
                    else:
                        self.dataset.finish_with_error("Whisper Error; unable to process request")
                        self.log.error("Whisper Error: " + str(result.json()))
                        return

        # Load the video metadata if available
        video_metadata = None
        if staging_area.joinpath(".video_metadata.json").is_file():
            with open(staging_area.joinpath(".video_metadata.json")) as file:
                video_metadata = json.load(file)
                self.dataset.log("Found and loaded video metadata")

        self.dataset.update_status("Processing Whisper results...")
        rows = []
        for result_filename in os.listdir(output_dir):
            with open(output_dir.joinpath(result_filename), "r") as result_file:
                result_data = json.loads(''.join(result_file.readlines()))
                row = {
                    "filename": result_filename,
                    "text": result_data["text"],
                    "language": result_data["language"],
                    "segments": ",\n".join([f"text: {segment['text']} (start: {segment['start']}; end: {segment['end']})" for segment in result_data['segments']])
                }
                if video_metadata:
                    video_name = ".".join(result_filename.split(".")[:-1])
                    audio_metadata = video_metadata.get(video_name)
                    row["video_url"] = audio_metadata.get("url")
                    row["post_ids"] = ", ".join(audio_metadata.get("post_ids"))
                    row["from_dataset"] = audio_metadata.get("from_dataset")

                rows.append(row)

        if rows:
            self.dataset.update_status(f"Detected speech in {len(rows)} of {total_audio_files} audio files")
            self.write_csv_items_and_finish(rows)
        else:
            return self.dataset.finish_with_error("No speech detected by Whisper.")

    @staticmethod
    def count_result_files(directory):
        """
        Get number of files in directory
        """
        return len(os.listdir(directory))
