"""
Convert speech in audio to text
"""
import os
import json

from backend.lib.processor import BasicProcessor
from common.lib.dmi_service_manager import DmiServiceManager, DmiServiceManagerException, DsmOutOfMemory
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.user_input import UserInput
from common.lib.item_mapping import MappedItem

from requests.exceptions import ConnectionError

import openai

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class AudioToText(BasicProcessor):
    """
    Convert audio to text with Whisper / GPT models, locally or through the OpenAI API
    """
    type = "audio-to-text"  # job type ID
    category = "Audio"  # category
    title = "Audio to text"  # title displayed in UI
    description = ("Detect speech and other sounds in audio and convert to text with either OpenAI's Whisper or "
                   " GPT models (GPT only via API).")  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI

    followups = []

    local_whisper = True if (config.get("dmi-service-manager.bc_whisper_enabled", False) and
                    config.get("dmi-service-manager.ab_server_address", False)) else False

    references = [
        "[OpenAI Whisper blog](https://openai.com/research/whisper)",
        "[OpenAI speech to text](https://github.com/openai/whisper/blob/248b6cb124225dd263bb9bd32d060b6517e067f8/whisper"
        "/transcribe.py#LL374C3-L374C3)",
        "[Whisper paper: Robust Speech Recognition via Large-Scale Weak Supervision](https://arxiv.org/abs/2212.04356)",
        "[OpenAI Whisper statistics & code](https://github.com/openai/whisper#whisper)",
        "[How to use prompts](https://platform.openai.com/docs/guides/speech-to-text/prompting)",
        ]

    config = {
        "dmi-service-manager.bb_whisper-intro-1": {
            "type": UserInput.OPTION_INFO,
            "help": "Whisper converts speech in audio to text. For a local model, ensure the DMI Service Manager is "
                    "running and has a [prebuilt Whisper image](https://github.com/digitalmethodsinitiative/dmi_docker"
                    "ized_services/tree/main/openai_whisper#dmi-implementation-of-whisper-audio-transcription-tool)."
                    " If no local model is configured, this processor uses the OpenAI API. Note that audio will be sent"
                    " to the OpenAI servers.",
        },
        "dmi-service-manager.bc_whisper_enabled": {
            "type": UserInput.OPTION_TOGGLE,
            "default": True,
            "help": "Use local Whisper model",
        },
        "dmi-service-manager.bd_whisper_num_files": {
            "type": UserInput.OPTION_TEXT,
            "coerce_type": int,
            "default": 0,
            "help": "Max number of audio files",
            "tooltip": "Use '0' to allow unlimited number"
        }
    }

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Allow on audio archives
        """
        return module.get_media_type() == 'audio' or module.type.startswith("audio-extractor")

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
        """
        Collect maximum number of audio files from configuration and update options accordingly
        :param config:
        """
        options = {
            "host_model_info": {
                "type": UserInput.OPTION_INFO,
                "help": "Local Whisper models can be enabled through the DMI Service Manager (Settings -> DMI Service "
                        "Manager)"
            },
            "model_host": {
                "type": UserInput.OPTION_CHOICE,
                "default": "local",
                "options": {"local": "Local", "external": "External (OpenAI API)"},
                "help": "Model type",
                "tooltip": "Local Whisper models need to be configured in settings."
            },
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "requires": "model_host==local"
            },
            "local_model": {
                # Whisper model options
                # TODO: Could limit model availability in conjunction with "amount"
                "type": UserInput.OPTION_CHOICE,
                "help": "Whisper model",
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
                "requires": "model_host==local"
            },
            "external_model": {
                "type": UserInput.OPTION_CHOICE,
                "help": f"Model",
                "default": "gpt-4o-mini-transcribe",
                "tooltip": "GPT-4o generally outperforms Whisper",
                "options": {
                    "gpt-4o-transcribe": "GPT-4o",
                    "gpt-4o-mini-transcribe": "GPT-4o mini",
                    "whisper-1": "Whisper V2"
                },
                "requires": "model_host==external"
            },
            "prompt": {
                "type": UserInput.OPTION_TEXT,
                "help": "Prompt",
                "default": "",
                "tooltip": "Optional; prompts can aid the model in specific vocabulary detection or to add punctuation "
                           "and filler words."
            },
            "language": {
                "type": UserInput.OPTION_TEXT,
                "help": "Language of audio",
                "default": "",
                "tooltip": "Optional; can help performance and latency. Use ISO-693-1 format (e.g. 'en').",
                "requires": "model_host==external"
            },
            "translate": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Translate transcriptions to English",
                "default": False,
                "tooltip": "Not supported by GPT models"
            },
            "advanced": {
                "type": UserInput.OPTION_TEXT_JSON,
                "help": "[Advanced settings](https://github.com/openai/whisper/blob/248b6cb124225dd263bb9bd32d060b6517e"
                        "067f8/whisper/transcribe.py#LL374C3-L374C3)",
                "default": {},
                "tooltip": "Additional settings can be provided as a JSON e.g., {\"--no_speech_threshold\": 0.2, "
                           "\"--logprob_threshold\": -0.5}.",
                "requires": "model_host==local"
            },
            "save_annotations": {
				"type": UserInput.OPTION_TOGGLE,
				"help": "Add transcriptions as annotations to top dataset",
				"default": False
			}
        }

        if cls.local_whisper:
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
        else:
            options["model_host"]["options"] = {"external": "External (OpenAI API)"}
            options["model_host"]["default"] = "external"

        api_key = config.get("api.openai.api_key", user=user)
        if not api_key:
            options["api_key"] = {
                "type": UserInput.OPTION_TEXT,
                "default": "",
                "help": "OpenAI API key",
                "tooltip": "Can be created on platform.openapi.com",
                "requires": "model_host==external",
                "sensitive": True
            }

        return options

    def process(self):
        """
        This takes a zipped set of audio files and uses a Whisper docker image to identify speech and convert to text,
        or calls the OpenAI API.
        """
        if self.source_dataset.num_rows <= 1:
            # 1 because there is always a metadata file
            self.dataset.finish_with_error("No audio files found.")
            return

        model_host = self.parameters.get("model_host", "external")

        if model_host == "local" and not self.local_whisper:
            self.dataset.finish_with_error("Can't run a self-hosted Whisper model. Admins can configure this in the "
                                           "4CAT settings (settings -> DMI Service Manager).")
            return

        api_key = self.parameters.get("api_key")
        if not api_key and model_host == "external":
            api_key = config.get("api.openai.api_key", user=self.owner)
        elif model_host == "external":
            self.dataset.finish_with_error("You need to provide a valid API key when using an external model")
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
        audio_filenames = [filename for filename in os.listdir(staging_area)
                           if filename.split('.')[-1] not in ["json", "log"]]
        if self.parameters.get("amount", 100) != 0:
            audio_filenames = audio_filenames[:self.parameters.get("amount", 100)]
        total_audio_files = len(audio_filenames)

        prompt = self.parameters.get("prompt", "")
        translate = self.parameters.get("translate", False)
        save_annotations = self.parameters.get("save_annotations", False)

        # Initialize DMI Service Manager when using local model
        if model_host != "external":
            dmi_service_manager = DmiServiceManager(processor=self)

            # Check connection and GPU memory available
            try:
                gpu_response = dmi_service_manager.check_gpu_memory_available("blip2")
            except DmiServiceManagerException as e:
                if "GPU not enabled on this instance of DMI Service Manager" in str(e):
                    self.dataset.update_status(
                        "GPU not enabled on this instance of DMI Service Manager; this may be a minute...")
                    gpu_response = None
                else:
                    return self.dataset.finish_with_error(str(e))
            except ConnectionError as e:
                self.dataset.finish_with_error("Can't reach DMI Service Manager.")
                return

            if gpu_response and int(gpu_response.get("memory", {}).get("gpu_free_mem", 0)) < 1000000:
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
                             "--model", self.parameters.get("local_model")],
                    }
            if prompt:
                data["args"].extend(["--initial_prompt", prompt])
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

            # Download the result files
            dmi_service_manager.process_results(output_dir)

        # Use API
        else:

            self.dataset.update_status("Getting transcriptions from OpenAI")

            external_model = self.parameters.get("external_model", "gpt-4o-mini-transcribe")
            language = self.parameters.get("language", "")

            client = openai.OpenAI(api_key=api_key)

            # Get response
            audio_filenames = [filename for filename in os.listdir(staging_area) if
                               filename.split('.')[-1] not in ["json", "log"]]

            # Translation if only available for Whisper
            if translate and external_model != "whisper-1":
                self.dataset.finish_with_error("Translation is only supported by Whisper for now")
                return

            for i, audio_filename in enumerate(audio_filenames):
                with open(os.path.join(staging_area, audio_filename), "rb") as f:

                    if not translate:
                        response = self.get_openai_api_transcription(
                            f,
                            model=external_model,
                            prompt=prompt,
                            language=language,
                            client=client
                        )
                    else:
                        response = self.get_openai_api_translation(
                            f,
                            prompt=prompt,
                            client=client
                        )

                    transcription = {
                        "text": response.text,
                        "language": language
                    }
                    f.close()

                    out_file = audio_filename.split(".")[0] + ".json"
                    with open(output_dir.joinpath(out_file), "w") as transcription_json:
                        json.dump(transcription, transcription_json)
                        transcription_json.close()

                s = "" if i == 0 else "s"
                self.dataset.update_status(f"Got {i + 1} transcription{s} from OpenAI")

        # Load the video metadata if available
        video_metadata = None
        if staging_area.joinpath(".video_metadata.json").is_file():
            with open(staging_area.joinpath(".video_metadata.json")) as file:
                video_metadata = json.load(file)
                self.dataset.log("Found and loaded video metadata")

        self.dataset.update_status("Processing results...")

        # Save files as NDJSON, then use map_item for 4CAT to interact
        processed = 0
        annotations = []
        with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile:
            for result_filename in os.listdir(output_dir):
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while writing results to file")

                self.dataset.log(f"Writing {result_filename}...")
                with open(output_dir.joinpath(result_filename), "r") as result_file:
                    result_data = json.loads("".join(result_file))
                    audio_name = ".".join(result_filename.split(".")[:-1])
                    audio_metadata = video_metadata.get(audio_name, {}) if video_metadata else {}
                    fourcat_metadata = {
                        "audio_id": audio_name,
                        # TODO: need to pass along filename/videoname/postid/SOMETHING consistent
                        "audio_metadata": audio_metadata,
                    }
                    result_data.update({"4CAT_metadata": fourcat_metadata})
                    outfile.write(json.dumps(result_data) + "\n")

                    if save_annotations:
                        for item_id in audio_metadata.get("post_ids", []):
                            annotations.append({
                                "label": "audio transcription",
                                "item_id": item_id,
                                "value": result_data.get("text", ""),
                                "type": "textarea"
                            })

                    processed += 1

        if save_annotations:
            self.dataset.update_status(f"Writing annotations")
            self.save_annotations(annotations, overwrite=False)

        self.dataset.update_status(f"Detected speech in {processed} of {total_audio_files} audio files")
        self.dataset.finish(processed)


    def get_openai_api_transcription(self, input_file, client, model="gpt-4o-mini-transcribe", language="", prompt=""):
        """
		Gets a transcription from the OpenAI API.
		:param input_file:      Location of input audio file.
		:param client:          OpenAI API client.
		:param model:           OpenAI model. Can be gpt-4o-mini-transcribe, gpt-4o-transcribe, or whisper-1.
		:param language:        Indicated language. Can help with performance.
		:param prompt:          Prompt text. Can help with performance.

		see https://platform.openai.com/docs/api-reference/audio/createTranscription

		returns: response
		"""
        try:
            # Get response
            response = client.audio.transcriptions.create(
                file=input_file,
                model=model,
                temperature=0,
                language=language,
                response_format="json",
                prompt=prompt
            )
        except openai.NotFoundError as e:
            self.dataset.finish_with_error(e.message)
            return
        except openai.BadRequestError as e:
            self.dataset.finish_with_error(e.message)
            return
        except openai.AuthenticationError as e:
            self.dataset.finish_with_error(e.message)
            return
        except openai.RateLimitError as e:
            self.dataset.finish_with_error(e.message)
            return
        except openai.APIConnectionError as e:
            self.dataset.finish_with_error(e.message)
            return

        return response

    def get_openai_api_translation(self, input_file, client, language="",
                                     prompt=""):
        """
        Gets a transcription from the OpenAI API.
        :param input_file:      Location of input audio file.
        :param client:          OpenAI API client.
        :param model:           OpenAI model. Can be gpt-4o-mini-transcribe, gpt-4o-transcribe, or whisper-1.
        :param language:        Indicated language. Can help with performance.
        :param prompt:          Prompt text. Can help with performance.

        see https://platform.openai.com/docs/api-reference/audio/createTranscription

        returns: response
        """
        try:
            # Get response
            response = client.audio.translations.create(
                file=input_file,
                model="whisper-1",
                temperature=0,
                response_format="json",
                prompt=prompt
            )
        except openai.NotFoundError as e:
            self.dataset.finish_with_error(e.message)
            return
        except openai.BadRequestError as e:
            self.dataset.finish_with_error(e.message)
            return
        except openai.AuthenticationError as e:
            self.dataset.finish_with_error(e.message)
            return
        except openai.RateLimitError as e:
            self.dataset.finish_with_error(e.message)
            return
        except openai.APIConnectionError as e:
            self.dataset.finish_with_error(e.message)
            return

        return response

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
