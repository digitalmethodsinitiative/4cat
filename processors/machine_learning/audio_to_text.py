"""
Convert speech in audio to text
"""
import os
import json
import openai
from requests.exceptions import ConnectionError

from backend.lib.processor import BasicProcessor
from common.lib.dmi_service_manager import DmiServiceManager, DmiServiceManagerException, DsmOutOfMemory
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.user_input import UserInput
from common.lib.item_mapping import MappedItem

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
        },
        "dmi-service-manager.be_whisper_gpu": {
            "type": UserInput.OPTION_TOGGLE,
            "default": True,
            "help": "Use GPU for Whisper processing",
        }
    }

    @classmethod
    def get_queue_id(cls, remote_id, details, dataset) -> str:
        """
        Shared queue for locally hosted models

        :param str remote_id:  Job item ID
        :param dict details:  Job details
        :param DataSet dataset:  Dataset to run job for
        :return:
        """
        # Unique queue for locally hosted models; used by other local model processors as well
        local_queue = "local_models" 
        if not dataset:
            return local_queue
        else:
            if dataset.parameters.get('model_host', 'local') in ["local"]:
                # Hosted models also go in the local queue since they use the same shared LLM server
                return local_queue
        
        # Queue per model/API type
        return f"{cls.type}-{dataset.parameters.get('model_host', 'local')}"

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
        local_whisper = (
            True
            if (
                config.get("dmi-service-manager.bc_whisper_enabled", False)
                and config.get("dmi-service-manager.ab_server_address", False)
            )
            else False
        )

        # Host options
        options = {
            "model_host": {
                "type": UserInput.OPTION_CHOICE,
                "default": "local" if local_whisper else "openai",
                "options": {"openai": "OpenAI API"}  | ({"local": "Local (DMI Service Manager)"} if local_whisper else {}),
                "help": "Model type",
                "tooltip": "Local Whisper models require DMI Service Manager to be running and configured in settings."
            },
        }
            
        if local_whisper:
            options.update({
                "amount_local": {
                    "type": UserInput.OPTION_TEXT,
                    "requires": "model_host==local"
                },
                "local_model": {
                    # Whisper model options
                    "type": UserInput.OPTION_CHOICE,
                    "help": "Whisper model",
                    "default": "small",
                    "tooltip": "Larger sizes increase quality at expense of greatly increasing the amount of time to process. Try the Small model and increase as needed.",
                    "options": {
                        "small.en": "Small English",
                        "small": "Small Detect Language",
                        "medium.en": "Medium English",
                        "medium": "Medium Detect Language",
                        "large": "Large Detect Language"
                    },
                    "requires": "model_host==local"
                },
                "translate": {
                    "type": UserInput.OPTION_TOGGLE,
                    "help": "Translate transcriptions to English",
                    "default": False,
                    "requires": "model_host==local"
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
            })
            # Update the Local audio amount max and help from config
            max_number_audio_files = int(config.get("dmi-service-manager.bd_whisper_num_files", 100))
            if max_number_audio_files == 0:  # Unlimited allowed
                options["amount_local"]["help"] = "Number of audio files"
                options["amount_local"]["default"] = 100
                options["amount_local"]["min"] = 0
                options["amount_local"]["tooltip"] = "Use '0' to convert all audio (this can take a very long time)"
            else:
                options["amount_local"]["help"] = f"Number of audio files (max {max_number_audio_files})"
                options["amount_local"]["default"] = min(max_number_audio_files, 100)
                options["amount_local"]["max"] = max_number_audio_files
                options["amount_local"]["min"] = 1

        # Universal and OpenAI API options
        options.update({
            # No max for external since we won't be processing the files in 4CAT and can rely on OpenAI's limits
            # User may want to limit (e.g. for cost reasons)
            "amount_external": {
                "type": UserInput.OPTION_TEXT,
                "default": 0,
                "min": 0,
                "help": "Number of audio files to convert (0 will convert all)",
                "tooltip": "Use '0' to convert all audio (this can take a very long time)",
                "requires": "model_host==openai"
            },
            "openai_action": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Action to perform with OpenAI API",
                "default": "transcribe",
                "options": {
                    "transcribe": "Transcribe",
                    "translate": "Translate",
                    "diarize": "Diarize (Speaker identification)"
                },
                "requires": "model_host==openai",
                "tooltip": "Transcription converts speech to text in the original language. Translation converts speech to English text (only available with Whisper V2). Diarization separates speakers and attempts to group them by speaker (only available with GPT-4o Diarization)."
            },
            "openai_transcribe_model": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Model",
                "default": "gpt-4o-transcribe",
                "tooltip": "GPT-4o generally outperforms Whisper",
                "options": {
                    "gpt-4o-transcribe": "GPT-4o",
                    "gpt-4o-mini-transcribe": "GPT-4o mini",
                    "whisper-1": "Whisper V2"
                },
                "requires": "model_host==openai&&openai_action==transcribe"
            },
            "openai_translate_model": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Model",
                "default": "whisper-1",
                "tooltip": "Whisper V2 is currently the only model that supports translation",
                "options": {
                    "whisper-1": "Whisper V2"
                },
                "requires": ["model_host==openai", "openai_action==translate"]
            },
            "openai_diarize_model": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Model",
                "default": "gpt-4o-transcribe-diarize",
                "tooltip": "GPT-4o Diarization is currently the only model that supports diarization",
                "options": {
                    "gpt-4o-transcribe-diarize": "GPT-4o Diarization",
                },
                "requires": ["model_host==openai", "openai_action==diarize"]
            },
            "prompt": {
                "type": UserInput.OPTION_TEXT,
                "help": "Prompt (optional)",
                "default": "",
                "tooltip": "Prompts can aid the model in specific vocabulary detection or to add punctuation"
                           "and filler words."
            },
            "language": {
                "type": UserInput.OPTION_TEXT,
                "help": "Language of audio",
                "default": "",
                "tooltip": "Optional; can help performance and latency. Use ISO-693-1 format (e.g. 'en').",
                "requires": "model_host==openai"
            },
            "save_annotations": {
                "type": UserInput.OPTION_ANNOTATION,
                "label": "Audio transcription",
                "tooltip": "Add transcriptions to top dataset",
                "default": False
            }
        })

        # Check for 4CAT wide API key if using OpenAI models
        api_key = config.get("api.openai.api_key")
        if not api_key:
            options["api_key"] = {
                "type": UserInput.OPTION_TEXT,
                "default": "",
                "help": "OpenAI API key",
                "tooltip": "Can be created on platform.openapi.com",
                "requires": "model_host==openai",
                "sensitive": True
            }

        return options

    def process(self):
        """
        This takes a zipped set of audio files and uses a Whisper docker image to identify speech and convert to text,
        or calls the OpenAI API.
        """
        skipped_items = 0
        model_host = self.parameters.get("model_host", "openai")

        local_whisper = (
            True
            if (
                self.config.get("dmi-service-manager.bc_whisper_enabled", False)
                and self.config.get("dmi-service-manager.ab_server_address", False)
            )
            else False
        )

        # Check settings and configuration based on host type
        if model_host == "local":
            if not local_whisper:
                self.dataset.finish_with_error("Can't run a self-hosted Whisper model. Admins can configure this in the "
                                               "4CAT settings (settings -> DMI Service Manager).")
                return
            
            # Check DMI Service Manager configuration if using local model
            dmi_service_manager = DmiServiceManager(processor=self)

            # Check connection and GPU memory available
            try:
                gpu_response = dmi_service_manager.check_gpu_memory_available("whisper")
            except DmiServiceManagerException as e:
                if "GPU not enabled on this instance of DMI Service Manager" in str(e):
                    self.dataset.update_status(
                        "GPU not enabled on this instance of DMI Service Manager; this may be a minute...")
                    gpu_response = None
                else:
                    return self.dataset.finish_with_error(str(e))
            except ConnectionError:
                self.dataset.finish_with_error("Can't reach DMI Service Manager.")
                return

            if gpu_response and int(gpu_response.get("memory", {}).get("gpu_free_mem", 0)) < 10000000:
                # is_final to avoid status overwritten (flag should be resent when job is claimed again)
                self.dataset.update_status("DMI Service Manager currently busy; no GPU memory available. Trying again later.", is_final=True)
                # Release job here (do not set self.interrupted or self.abort will release 10 seconds or finish the job)
                self.job.release(delay=60)  # Try again in a minute
                raise ProcessorInterruptedException("DMI Service Manager GPU busy")
        
            # Check advanced_settings
            advanced_settings = self.parameters.get("advanced", {})
            if type(advanced_settings) is str:
                try:
                    advanced_settings = json.loads(advanced_settings)
                except ValueError:
                    self.dataset.finish_with_error("Unable to parse Advanced settings. Please format as JSON.")
                    return

        else:
            # Check for API key if using OpenAI models
            api_key = self.parameters.get("api_key")
            if not api_key:
                api_key = self.config.get("api.openai.api_key")
            if not api_key and model_host == "openai":
                self.dataset.finish_with_error("You need to provide a valid API key when using an OpenAI model")
                return

        # Unpack the audio files into a staging_area
        self.dataset.update_status("Unzipping audio files")
        staging_area = self.unpack_archive_contents(self.source_file)
        # Prepare output dir
        output_dir = self.dataset.get_staging_area()

        # Collect filenames (skip .json metadata files)
        audio_filenames = [filename for filename in os.listdir(staging_area)
                           if filename.split('.')[-1] not in ["json", "log"]]
        total_audio_files = len(audio_filenames)

        prompt = self.parameters.get("prompt", "")
        save_annotations = self.parameters.get("save_annotations", False)
        # Initialize DMI Service Manager when using local model
        if model_host == "local":
            translate = self.parameters.get("translate", False)

            # Update amount based on config max if needed
            if self.parameters.get("amount_local", 100) != 0:
                max_files = min(self.parameters.get("amount_local", 100), len(audio_filenames))
                audio_filenames = audio_filenames[:max_files]
                total_audio_files = len(audio_filenames)

            # Provide audio files to DMI Service Manager
            # Results should be unique to this dataset
            results_folder_name = f"texts_{self.dataset.key}"
            # Files can be based on the parent dataset (to avoid uploading the same files multiple times)
            file_collection_name = dmi_service_manager.get_folder_name(self.source_dataset)

            path_to_files, path_to_results = dmi_service_manager.process_files(staging_area, audio_filenames,
                                                                               output_dir, file_collection_name,
                                                                               results_folder_name)

            # Whisper args
            whisper_endpoint = "whisper"
            data = {"args": ['--output_dir', f"data/{path_to_results}",
                             "--verbose", "False",
                             '--output_format', "json",
                             "--model", self.parameters.get("local_model")],
                    }
            if not self.config.get("dmi-service-manager.be_whisper_gpu", True):
                data["args"].extend(["--device", "cpu"])
            if prompt:
                data["args"].extend(["--initial_prompt", prompt])
            if translate:
                data["args"].extend(["--task", 'translate'])
            if advanced_settings:
                for setting, value in advanced_settings.items():
                    setting = setting if setting[:2] == "--" else "--" + setting.lstrip("-")
                    data["args"].extend([setting, str(value)])
            # Finally, add audio files to args
            data["args"].extend(
                [f"data/{path_to_files.joinpath(dmi_service_manager.sanitize_filenames(filename))}" for filename in
                 audio_filenames])

            # Send request to DMI Service Manager
            self.dataset.update_status("Requesting service from DMI Service Manager...")
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

        # Use OpenAI API
        else:
            self.dataset.update_status("Getting transcriptions from OpenAI")
            max_files = self.parameters.get("amount_external", 0)
            max_files = max_files if max_files != 0 else total_audio_files

            openai_action = self.parameters.get("openai_action", "transcribe")
            translate = openai_action == "translate"

            # Resolve the actual model to use based on action-specific parameters.
            # Resolution order: action-specific param -> legacy `openai_model` -> code default.
            if openai_action == "transcribe":
                selected_model = self.parameters.get(
                    "openai_transcribe_model",
                    self.parameters.get("openai_model", "gpt-4o-mini-transcribe")
                )
            elif openai_action == "translate":
                selected_model = self.parameters.get(
                    "openai_translate_model",
                    self.parameters.get("openai_model", "whisper-1")
                )
            elif openai_action == "diarize":
                selected_model = self.parameters.get(
                    "openai_diarize_model",
                    self.parameters.get("openai_model", "gpt-4o-transcribe-diarize")
                )
            else:
                # Default fallback (shouldn't really be needed)
                selected_model = self.parameters.get("openai_model", "gpt-4o-mini-transcribe")
            language = self.parameters.get("language", "")

            client = openai.OpenAI(api_key=api_key)

            # Fallback checks for action-model compatibility (in case of misconfiguration or legacy `openai_model` usage)
            if translate and selected_model != "whisper-1":
                self.dataset.finish_with_error("Translation is only supported by Whisper for now")
                return
            elif openai_action == "diarize" and selected_model != "gpt-4o-transcribe-diarize":
                self.dataset.finish_with_error("Diarization is only supported by GPT-4o Diarization for now")
                return

            for i, audio_filename in enumerate(audio_filenames):
                if self.interrupted:
                    # Stop process, but processes results
                    skipped_items += len(audio_filenames) - i
                    self.dataset.update_status("Analysis interrupted while processing audio files.")
                    break
                
                if max_files != 0 and (i - skipped_items >= max_files):
                    self.dataset.update_status(f"Reached the maximum number of audio files to process ({max_files}).")
                    break
                
                with open(os.path.join(staging_area, audio_filename), "rb") as f:
                    try:
                        if openai_action == "transcribe":
                            # Returns Transcription (json) or TranscriptionVerbose (verbose_json).
                            # verbose_json adds language, duration, segments, and words but is whisper-1 only.
                            result = self.get_openai_api_transcription(
                                f,
                                client=client,
                                model=selected_model,
                                prompt=prompt,
                                language=language,
                            )
                        elif openai_action == "diarize":
                            # Returns TranscriptionDiarized (diarized_json).
                            result = self.get_openai_api_diarization(
                                f,
                                client=client,
                                model=selected_model,
                                prompt=prompt,
                                language=language,
                            )
                        elif openai_action == "translate":
                            # Returns Translation (json) — only field is text.
                            result = self.get_openai_api_translation(
                                f,
                                client=client,
                                model=selected_model,
                                prompt=prompt,
                                language=language,
                            )
                        else:
                            self.dataset.finish_with_error("Invalid OpenAI action specified.")
                            return

                        # All SDK response types are Pydantic BaseModel instances.
                        # model_dump() serializes every field the API returned.
                        transcription = result.model_dump()

                    except (openai.NotFoundError, openai.BadRequestError, openai.AuthenticationError,
                            openai.RateLimitError, openai.APIConnectionError) as e:
                        skipped_items += 1
                        error_msg = f"OpenAI API error for file {audio_filename}: {e.message}"
                        self.dataset.log(error_msg)
                        transcription = {"text": "", "errors": [error_msg]}
                    except Exception as e:
                        skipped_items += 1
                        error_msg = f"Unexpected error for file {audio_filename}: {str(e)}"
                        self.dataset.log(error_msg)
                        transcription = {"text": "", "errors": [error_msg]}

                out_file = audio_filename.split(".")[0] + ".json"
                with open(output_dir.joinpath(out_file), "w") as transcription_json:
                    json.dump(transcription, transcription_json)

                s = "" if i == 0 else "s"
                self.dataset.update_status(f"Got {i + 1} transcription{s} from OpenAI")
                self.dataset.update_progress((i + 1) / max_files)

        # Load the video metadata if available
        video_metadata = None
        if staging_area.joinpath(".metadata.json").is_file():
            with open(staging_area.joinpath(".metadata.json")) as file:
                video_metadata = json.load(file)
                self.dataset.log("Found and loaded video metadata")

        self.dataset.update_status("Processing results...")

        # Save files as NDJSON, then use map_item for 4CAT to interact
        processed = 0
        annotations = []
        self.dataset.update_status("Saving results to dataset...")
        with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile:
            for result_filename in os.listdir(output_dir):
                # Do not check interrupt; save completed results
                with open(output_dir.joinpath(result_filename), "r") as result_file:
                    result_data = json.loads("".join(result_file))
                    audio_name = ".".join(result_filename.split(".")[:-1])
                    audio_metadata = video_metadata.get(audio_name, {}) if video_metadata else {}
                    fourcat_metadata = {
                        "audio_id": audio_name,
                        "model_host": model_host,
                        "model": (selected_model if model_host == "openai" else self.parameters.get("local_model")),
                        "auto_translate": translate if model_host == "local" else (openai_action == "translate" if model_host == "openai" else False),
                        "openai_action": openai_action if model_host == "openai" else None,
                        "audio_metadata": audio_metadata,
                    }
                    result_data.update({"4CAT_metadata": fourcat_metadata})
                    outfile.write(json.dumps(result_data) + "\n")

                if save_annotations:
                    for item_id in audio_metadata.get("post_ids", []):
                        annotations.append({
                            "label": "Audio transcription",
                            "item_id": item_id,
                            "value": result_data.get("text", "")
                        })

                processed += 1

        if save_annotations:
            self.dataset.update_status(f"Saving transcriptions as annotations on {len(annotations)} posts...")
            self.save_annotations(annotations)

        if skipped_items > 0:
            self.dataset.finish_with_warning(processed, f"Completed {processed} file{'s' if processed != 1 else ''}. Skipped {skipped_items} file{'s' if skipped_items != 1 else ''}.")
        else:
            self.dataset.update_status(f"Detected speech in {processed} of {total_audio_files} audio files", is_final=True)
            self.dataset.finish(processed)

    def get_openai_api_transcription(self, input_file, client, model="gpt-4o-mini-transcribe", language="", prompt=""):
        """
        Request a transcription from the OpenAI audio API.

        Returns a Transcription or TranscriptionVerbose SDK object (Pydantic BaseModel).

        whisper-1 supports response_format="verbose_json", which returns a TranscriptionVerbose
        with: text, language, duration, segments (TranscriptionSegment list), words, usage.

        gpt-4o-transcribe and gpt-4o-mini-transcribe only support response_format="json", which
        returns a Transcription with: text, logprobs (optional), usage (optional).

        See https://platform.openai.com/docs/api-reference/audio/createTranscription
        """
        # whisper-1 supports verbose_json, which returns the richer TranscriptionVerbose object
        # (language, duration, segments, words). GPT-4o models only support json.
        response_format = "verbose_json" if model == "whisper-1" else "json"
        return client.audio.transcriptions.create(
            file=input_file,
            model=model,
            temperature=0,
            language=language,
            response_format=response_format,
            prompt=prompt
        )

    def get_openai_api_diarization(self, input_file, client, model="gpt-4o-transcribe-diarize", prompt="", language=""):
        """
        Request a diarized transcription from the OpenAI audio API.

        Returns a TranscriptionDiarized SDK object (Pydantic BaseModel) with:
        text, duration, task, segments (TranscriptionDiarizedSegment list), usage (optional).

        Each TranscriptionDiarizedSegment has: id, start, end, text, speaker, type.
        response_format="diarized_json" is required to receive speaker annotations.

        See https://platform.openai.com/docs/api-reference/audio/createTranscription
        """
        return client.audio.transcriptions.create(
            file=input_file,
            model=model,
            temperature=0,
            language=language,
            response_format="diarized_json",
            prompt=prompt,
            chunking_strategy="auto",
            # To send known speaker references for cross-file consistency, pass extra_body:
            # extra_body={
            #     "known_speaker_names": ["Alice", "Bob"],
            #     "known_speaker_references": [to_data_url("alice.wav"), to_data_url("bob.wav")],
            # },
        )

    def get_openai_api_translation(self, input_file, client, language="",
                                   prompt="", model="whisper-1"):
        """
        Request a translation to English from the OpenAI audio API.

        Returns a Translation SDK object (Pydantic BaseModel) with a single field: text.
        Only whisper-1 supports translation.

        See https://platform.openai.com/docs/api-reference/audio/createTranslation
        """
        return client.audio.translations.create(
            file=input_file,
            model=model,
            temperature=0,
            response_format="json",
            prompt=prompt
        )

    @staticmethod
    def map_item(item):
        """
        Maps an NDJSON result item to a standardized MappedItem.

        The NDJSON is the result.model_dump() of the SDK response object merged with 4CAT_metadata.
        Supported SDK response schemas:
          - Transcription (json format):        text, logprobs?, usage?
          - TranscriptionVerbose (verbose_json): text, language, duration, segments?, words?, usage?
          - TranscriptionDiarized (diarized_json): text, duration, task, segments, usage?
          - Translation (json format):           text
          - Local whisper binary output:         text, language, segments?

        Segments are formatted differently depending on action:
          - Diarized: [Speaker] text (start; end)
          - All others: text (start; end)
        """
        fourcat_metadata = item.get("4CAT_metadata", {})
        audio_metadata = fourcat_metadata.get("audio_metadata", {})
        openai_action = fourcat_metadata.get("openai_action")

        # Format segments based on response type.
        # TranscriptionDiarizedSegment: {id, start, end, text, speaker, type}
        # TranscriptionSegment (verbose_json) and local whisper: {id, seek, start, end, text, tokens, ...}
        segments = item.get("segments") or []
        if openai_action == "diarize":
            segments_str = "\n".join(
                f"[{s.get('speaker', '?')}] {s.get('text', '')} "
                f"(start: {s.get('start')}; end: {s.get('end')})"
                for s in segments
            )
        else:
            segments_str = "\n".join(
                f"{s.get('text', '')} (start: {s.get('start')}; end: {s.get('end')})"
                for s in segments
            )

        # TranscriptionVerbose only: word-level timestamps {word, start, end}
        words = item.get("words") or []
        words_str = " ".join(w.get("word", "") for w in words)

        # Usage is optional and its shape depends on the billing type:
        # UsageTokens: {type, input_tokens, output_tokens, total_tokens, input_token_details?}
        # UsageDuration: {type, seconds}
        usage = item.get("usage")
        if usage:
            if usage.get("type") == "tokens":
                usage_str = (
                    f"tokens — input: {usage.get('input_tokens')}, "
                    f"output: {usage.get('output_tokens')}, "
                    f"total: {usage.get('total_tokens')}"
                )
            else:
                usage_str = f"duration: {usage.get('seconds')}s"
        else:
            usage_str = ""

        return MappedItem({
            "id": fourcat_metadata.get("audio_id"),
            "model_host": fourcat_metadata.get("model_host"),
            "model": fourcat_metadata.get("model"),
            "openai_action": openai_action,
            "auto_translate": fourcat_metadata.get("auto_translate"),
            "body": item.get("text", ""),
            # language is present in TranscriptionVerbose, TranscriptionDiarized, and local whisper output
            "language": item.get("language", ""),
            # duration is present in TranscriptionVerbose and TranscriptionDiarized
            "duration": item.get("duration", ""),
            "segments": segments_str,
            # words is only present in TranscriptionVerbose (whisper-1, verbose_json)
            "words": words_str,
            "usage": usage_str,
            "errors": ", ".join(item.get("errors") or []),
            "original_video_url": audio_metadata.get("url", ""),
            "post_ids": ", ".join(audio_metadata.get("post_ids", [])),
            "from_dataset": audio_metadata.get("from_dataset", "")
        })
