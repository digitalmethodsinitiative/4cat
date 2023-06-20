"""
Whisper convert speech in audio to text
"""
import datetime
import os
import json
import time
import requests
from pathlib import Path
from json import JSONDecodeError


from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorException, ProcessorInterruptedException
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
        # "host.docker.internal" if 4CAT Dockerized
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
        max_number_audio_files = int(config.get("dmi_service_manager.whisper_num_files", 100))
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

        local_or_remote = config.get("dmi_service_manager.local_or_remote")

        # Unpack the audio files into a staging_area
        self.dataset.update_status("Unzipping audio files")
        staging_area = self.unpack_archive_contents(self.source_file)

        # Collect filenames (skip .json metadata files)
        audio_filenames = [filename for filename in os.listdir(staging_area) if filename.split('.')[-1] not in ["json", "log"]]
        if self.parameters.get("amount", 100) != 0:
            audio_filenames = audio_filenames[:self.parameters.get("amount", 100)]
        total_audio_files = len(audio_filenames)

        # Make output dir
        output_dir = self.dataset.get_staging_area()

        # Send Request
        if local_or_remote == "local":
            # Whisper has direct access to files
            whisper_endpoint = "whisper_local"

            # Relative to PATH_DATA which should be where Docker mounts the whisper container volume
            # TODO: path is just the staging_area name, but what if we move staging areas? DMI Service manager needs to know...
            mounted_staging_area = staging_area.absolute().relative_to(config.get("PATH_DATA").absolute())
            mounted_output_dir = output_dir.absolute().relative_to(config.get("PATH_DATA").absolute())

        elif local_or_remote == "remote":
            # Upload files to whisper
            whisper_endpoint = "whisper_remote"

            texts_folder = f"texts_{self.dataset.key}"

            # Get labels to send server
            top_dataset = self.dataset.top_parent()
            folder_name = datetime.datetime.fromtimestamp(self.source_dataset.timestamp).strftime("%Y-%m-%d-%H%M%S") + '-' + \
                          ''.join(e if e.isalnum() else '_' for e in top_dataset.get_label()) + '-' + \
                          str(top_dataset.key)

            data = {'folder_name': folder_name}

            # Check if audio files have already been sent
            self.dataset.update_status("Connecting to DMI Service Manager...")
            filename_url = config.get("dmi_service_manager.server_address").rstrip("/") + '/api/list_filenames?folder_name=' + folder_name
            filename_response = requests.get(filename_url, timeout=30)

            # Check if 4CAT has access to this PixPlot server
            if filename_response.status_code == 403:
                self.dataset.update_status("403: 4CAT does not have permission to use the DMI Service Manager server",
                                           is_final=True)
                self.dataset.finish(0)
                return

            uploaded_audio_files = filename_response.json().get('audio', [])
            if len(uploaded_audio_files) > 0:
                self.dataset.update_status("Found %i audio files previously uploaded" % (len(uploaded_audio_files)))

            # Compare audio files with previously uploaded
            to_upload_filenames = [filename for filename in audio_filenames if filename not in uploaded_audio_files]

            if len(to_upload_filenames) > 0 or texts_folder not in filename_response.json():
                # TODO: perhaps upload one at a time?
                api_upload_endpoint = config.get("dmi_service_manager.server_address").rstrip("/") + "/api/send_files"
                # TODO: don't create a silly empty file just to trick the service manager into creating a new folder
                with open(staging_area.joinpath("blank.txt"), 'w') as file:
                    file.write('')
                self.dataset.update_status(f"Uploading {len(to_upload_filenames)} audio files")
                response = requests.post(api_upload_endpoint, files=[('audio', open(staging_area.joinpath(file), 'rb')) for file in to_upload_filenames] + [(texts_folder, open(staging_area.joinpath("blank.txt"), 'rb'))], data=data, timeout=120)
                if response.status_code == 200:
                    self.dataset.update_status(f"Audio files uploaded: {len(to_upload_filenames)}")
                else:
                    self.dataset.update_status(f"Unable to upload {len(to_upload_filenames)} files!")
                    self.log.error(f"Whisper upload error: {response.status_code} - {response.reason}")

            mounted_staging_area = Path(folder_name).joinpath("audio")
            mounted_output_dir = Path(folder_name).joinpath(texts_folder)

        else:
            raise ProcessorException("dmi_service_manager.local_or_remote setting must be 'local' or 'remote'")

        # Whisper args
        data = {"args": ['--output_dir', f"data/{mounted_output_dir}",
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
        data["args"].extend([f"data/{mounted_staging_area.joinpath(filename)}" for filename in audio_filenames])

        self.dataset.update_status(f"Requesting service from DMI Service Manager...")
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
                if local_or_remote == "local":
                    num_completed = self.count_result_files(output_dir)
                    if num_completed != prev_completed:
                        self.dataset.update_status(f"Collected text from {num_completed} of {total_audio_files} audio files")
                        self.dataset.update_progress(num_completed / total_audio_files)
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
        if local_or_remote == "local":
            # Output files are local
            pass
        elif local_or_remote == "remote":
            # Update list of uploaded files
            filename_response = requests.get(filename_url, timeout=30)
            result_files = filename_response.json().get(texts_folder, [])

            # Download the result files
            api_upload_endpoint = config.get("dmi_service_manager.server_address").rstrip("/") + "/api/uploads/"
            for filename in result_files:
                file_response = requests.get(api_upload_endpoint + f"{folder_name}/{texts_folder}/{filename}", timeout=30)
                self.dataset.log(f"Downloading {filename}...")
                with open(output_dir.joinpath(filename), 'wb') as file:
                    file.write(file_response.content)
        else:
            # This should have raised already...
            raise ProcessorException("dmi_service_manager.local_or_remote setting must be 'local' or 'remote'")

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
        return {
            "audio_id": fourcat_metadata.get("audio_id"),
            "text": item.get("text", ""),
            "language": item.get("language", ""),
            "segments": ",\n".join(
                [f"text: {segment['text']} (start: {segment['start']}; end: {segment['end']}; )" for segment in
                 item.get("segments", [])]),
            "original_video_url": audio_metadata.get("url", ""),
            "post_ids": ", ".join(audio_metadata.get("post_ids", [])),
            "from_dataset": audio_metadata.get("from_dataset", "")
        }

    @staticmethod
    def count_result_files(directory):
        """
        Get number of files in directory
        """
        return len(os.listdir(directory))
