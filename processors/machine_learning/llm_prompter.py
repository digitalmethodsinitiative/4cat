"""
Prompt LLMs.
"""

import re
import time
from datetime import datetime

from common.lib.exceptions import ProcessorInterruptedException
from common.lib.helpers import UserInput
from common.lib.llm import LLMAdapter
from backend.lib.processor import BasicProcessor

class LLMPrompter(BasicProcessor):
    """
    Prompt various LLMs, locally or through APIs
    """
    type = "llm-prompter"  # job type ID
    category = "Machine learning"  # category
    title = "LLM prompting"  # title displayed in UI
    description = ("Use LLMs for analysis, via APIs or locally. This can be used for tasks like classification or "
                   "entity extraction. Supported APIs include OpenAI, Google, Anthropic, and Mistral.")  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI. In this case it's variable!

    references = [
        "[Törnberg, Petter. 2023. 'How to Use LLMs for Text Analysis.' arXiv:2307.13106.](https://arxiv.org/pdf/2307.13106)",
        "[Karjus, Andres. 2023. 'Machine-assisted mixed methods: augmenting humanities and social sciences "
        "with artificial intelligence.' arXiv preprint arXiv:2309.14379.]"
        "(https://arxiv.org/abs/2309.14379)",
    ]

    @classmethod
    def get_options(cls, parent_dataset=None, config=None) -> dict:
        options = {
            "per_item": {
                "type": UserInput.OPTION_INFO,
                "help": "Prompts are ran per row. Use [brackets] with a column name to "
                "indicate what input value you want to use. For instance: 'Determine the language of the "
                "following text: [body]').",
            },
            "ethics_warning1": {
                "type": UserInput.OPTION_INFO,
                "help": "Consider testing your prompt on a handful of rows. You can sample your dataset with "
                "filtering processors.",
            },
            "api_or_local": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Local or API",
                "options": {"api": "API", "local": "Local"},
                "default": "api",
                "tooltip": "You can use 'local' models through Ollama and LM Studio as long as you have a valid "
                "and accessible URL through which the model can be reached.",
            },
            "api_model": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Model",
                "options": LLMAdapter.get_model_options(config),
                "default": "mistral-small-2503",
                "requires": "api_or_local==api",
            },
            "api_key": {
                "type": UserInput.OPTION_TEXT,
                "default": "",
                "help": "API key",
                "tooltip": "Create an API key on the LLM provider's website (e.g. https://admin.mistral.ai/organization/api-keys)",
                "requires": "api_or_local==api",
                "sensitive": True,
            },
            "api_custom_model_info": {
                "type": UserInput.OPTION_INFO,
                "requires": "api_model==custom",
                "help": "Most LLM providers allow fine-tuning your own custom model (e.g. through the [OpenAI portal]"
                "(https://platform.openai.com/docs/guides/fine-tuning). Fine-tuned models may perform better for"
                " specific analysis tasks.",
            },
            "api_custom_model_id": {
                "type": UserInput.OPTION_TEXT,
                "help": "Model ID",
                "requires": "api_model==custom",
                "tooltip": "Check the API provider's documentation on what model ID to use. OpenAI for instance requires"
                " the following format: ft:[modelname]:[org_id]:[custom_suffix]:",
            },
            "local_info": {
                "type": UserInput.OPTION_INFO,
                "requires": "api_or_local==local",
                "help": "You can use local LLMs with various applications. 4CAT currently supports LM Studio and Ollama. "
                        "These applications need to be reachable by this 4CAT server, e.g. by running them "
                        "locally on the same machine.",
            },
            "local_provider": {
                "type": UserInput.OPTION_CHOICE,
                "requires": "api_or_local==local",
                "options": {
                    "none": "",
                    "lmstudio": "LM Studio",
                    "ollama": "Ollama"
                },
                "default": "none",
                "help": "Local LLM provider",
            },
            "lmstudio-info": {
                "type": UserInput.OPTION_INFO,
                "requires": "local_provider==lmstudio",
                "help": "LM Studio is a desktop application to chat with LLMs, but that you can also run as a local "
                "server. See [this link for intructions on how to run LM Studio as a server](https://lmstudio.ai/docs/"
                "app/api). When the server is running, the endpoint is shown in the 'Developer' tab on the top "
                "right (default: http://localhost:1234/v1). 4CAT will use the top-most model you have loaded in",
            },
            "ollama-info": {
                "type": UserInput.OPTION_INFO,
                "requires": "local_provider==ollama",
                "help": "Ollama is a command-line application that you can also run as a local server. See [this link]"
                "(https://lmstudio.ai/docs/app/api) for instructions.",
            },
            "lmstudio_api_key": {
                "type": UserInput.OPTION_TEXT,
                "default": "",
                "help": "LM Studio API key",
                "tooltip": "Leaving this empty will use the default `lm-studio` key.",
                "requires": "local_provider==lmstudio",
                "sensitive": True,
            },
            "local_base_url": {
                "type": UserInput.OPTION_TEXT,
                "requires": "api_or_local==local",
                "default": "",
                "help": "Base URL for local models",
                "tooltip": "Leaving this empty will use default values (http://localhost:1234/v1 for LM Studio, "
                           "http://localhost:11434 for Ollama)",
            },
            "ollama_model": {
                "type": UserInput.OPTION_TEXT,
                "requires": "local_provider==ollama",
                "default": "",
                "help": "Ollama model name",
                "tooltip": "E.g. 'llama3.2:latest'",
            },
            "prompt": {
                "type": UserInput.OPTION_TEXT_LARGE,
                "help": "Prompt",
                "tooltip": "See the references for this processor on best practices for LLM prompts",
            },
            "temperature": {
                "type": UserInput.OPTION_TEXT,
                "help": "Temperature",
                "default": 0,
                "tooltip": "The temperature hyperparameter indicates how strict the model will gravitate towards the next "
                "predicted word with the highest probability. A score close to 0 returns more predictable "
                "outputs while a score close to 1 leads to more creative outputs.",
            },
            "max_tokens": {
                "type": UserInput.OPTION_TEXT,
                "help": "Max output tokens",
                "default": 50,
                "tooltip": "As a rule of thumb, one token generally corresponds to ~4 characters of "
                "text for common English text.",
            },
            "ethics_warning3": {
                "type": UserInput.OPTION_INFO,
                "requires": "api_or_local==api",
                "help": "<strong>When using LLMs through commercial parties, always consider anonymising your data and "
                "whether local open-source LLMs are also an option.</strong>",
            },
            "consent": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "I understand that my data is sent to the API provider and that they may incur costs.",
                "requires": "api_or_local==api",
                "default": False,
            },
            "save_annotations": {
                "type": UserInput.OPTION_ANNOTATION,
                "label": "prompt outputs",
                "default": False,
            },
        }

        return options

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Determine if processor is compatible with a dataset or processor

        :param module: Module to determine compatibility with
        """

        return module.get_extension() in ["csv", "ndjson"]

    def process(self):
        self.dataset.update_status("Connecting to LLM provider")

        api_consent = self.parameters.get("consent", False)
        api_model = self.parameters.get("api_model")
        use_local_model = True if self.parameters.get("api_or_local", "api") == "local" else False

        if not use_local_model and not api_consent:
            self.dataset.finish_with_error("You must consent to your data being sent to the LLM provider first")
            return

        self.dataset.delete_parameter("consent")

        if not use_local_model and api_model == "custom":
            if not self.parameters.get("custom_model", ""):
                self.dataset.finish_with_error(
                    "You must provide a valid ID for your custom model"
                )
                return
            else:
                custom_model_id = self.parameters.get("custom_model", "")
                self.parameters["model"] = custom_model_id
                model = custom_model_id

        if use_local_model:
            if self.parameters.get("local_provider") == "none":
                self.dataset.finish_with_error("Choose a local model provider")
                return
            model = "custom"

        try:
            temperature = float(self.parameters.get("temperature"))
        except ValueError:
            self.dataset.finish_with_error("Temperature must be a number")
            return

        try:
            max_tokens = int(self.parameters.get("max_tokens"))
        except ValueError:
            self.dataset.finish_with_error("Max tokens must be a number")
            return

        # Set all variables through which we can reach the LLM
        api_key = ""
        base_url = None
        if use_local_model:
            provider = self.parameters.get("local_provider", "")
            base_url = self.parameters.get("local_base_url", "")
            if provider == "lmstudio" and not self.parameters.get("lmstudio_api_key"):
                api_key = "lm-studio"
            if not base_url:
                if provider == "lmstudio":
                    base_url = "http://127.0.0.1:1234/v1"
                elif provider == "ollama":
                    base_url = "http://localhost:11434"

        else:
            provider = LLMAdapter.get_models(self.config)[api_model]["provider"]
            model = api_model
            api_key = self.parameters.get("api_key", "")
            if not api_key:
                api_key = self.config.get(f"api.{provider}.api_key", "")
            if not api_key:
                self.dataset.finish_with_error("You need to provide a valid API key")
                return

        if provider == "ollama":
            model = self.parameters.get("ollama_model", "")

        base_prompt = self.parameters.get("prompt", "")
        self.dataset.update_status("Prompt: %s" % base_prompt)

        if not base_prompt:
            self.dataset.finish_with_error("You need to insert a valid prompt")
            return

        replacements = re.findall(r"\[.*?\]", base_prompt)
        if not replacements:
            self.dataset.finish_with_error(
                "You need to provide the prompt with input values using [brackets] of "
                "column names"
            )
            return

        # Start LLM
        try:
            llm = LLMAdapter(provider=provider, model=model, api_key=api_key, base_url=base_url, temperature=temperature)
        except Exception as e:
            self.dataset.finish_with_error(str(e))
            return

        save_annotations = self.parameters.get("save_annotations", False)

        if save_annotations:
            label = model + " output" if model else "Local LLM output"

        results = []
        annotations = []

        i = 1
        for item in self.source_dataset.iterate_items():
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while generating text through LLMs")

            # Replace with dataset values
            prompt = base_prompt
            for replacement in replacements:
                try:
                    field_name = str(item[replacement[1:-1]]).strip()
                    prompt = prompt.replace(replacement, field_name)
                except KeyError as e:
                    self.dataset.finish_with_error("Field %s could not be found in the parent dataset" % str(e))
                    return

            try:
                response = llm.text_generation(prompt)
            except Exception as e:
                self.dataset.finish_with_error(str(e))
                return

            if "id" in item:
                item_id = item["id"]
            elif "item_id" in item:
                item_id = item["item_id"]
            else:
                item_id = str(i)

            time_created = time.time()
            results.append({
                "id": item_id,
                "prompt": prompt,
                model + " output": response,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "model": model,
                "time_created": datetime.fromtimestamp(time_created).strftime("%Y-%m-%d %H:%M:%S"),
                "time_created_utc": time_created
            })

            if save_annotations:
                annotation = {
                    "label": label,
                    "item_id": item_id,
                    "value": response,
                    "type": "textarea",
                }
                annotations.append(annotation)

            self.dataset.update_status(
                "Generated output for item %s/%s" % (i, self.source_dataset.num_rows)
            )
            i += 1

            # Rate limits for different providers
            if provider == "mistral":
                time.sleep(1)

        # Write annotations
        if save_annotations:
            self.save_annotations(annotations)

        # Write to csv file
        self.write_csv_items_and_finish(results)