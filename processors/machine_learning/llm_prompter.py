"""
Prompt LLMs.
"""

import re
import time
import json
import jsonschema
import requests

from json import JSONDecodeError
from jsonschema.exceptions import ValidationError, SchemaError
from datetime import datetime, timedelta

from common.lib.item_mapping import MappedItem
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.helpers import UserInput, nthify, andify, remove_nuls, flatten_dict
from common.lib.llm import LLMAdapter
from backend.lib.processor import BasicProcessor

class LLMPrompter(BasicProcessor):
    """
    Prompt various LLMs, locally or through APIs
    """
    type = "llm-prompter"  # job type ID
    category = "Machine learning"  # category
    title = "LLM prompting"  # title displayed in UI
    description = ("Use LLMs for analysis, via APIs or locally. This can be used for tasks like classification, "
                   "entity extraction, or OCR. Supported APIs include OpenAI, Google, Anthropic, Mistral, and DeepSeek.")
    extension = "ndjson"  # extension of result file, used internally and in UI. In this case it's variable!

    references = [
        "[Törnberg, Petter. 2023. 'How to Use LLMs for Text Analysis.' arXiv:2307.13106.](https://arxiv.org/pdf/2307."
        "13106)",
        "[Karjus, Andres. 2023. 'Machine-assisted mixed methods: augmenting humanities and social sciences "
        "with artificial intelligence.' arXiv preprint arXiv:2309.14379.]"
        "(https://arxiv.org/abs/2309.14379)"
    ]

    @classmethod
    def get_queue_id(cls, remote_id, details, dataset) -> str:
        """
        Get Queue ID

        Assigns a job for this worker to a different queue depending on whether
        it is interfacing with a 'local' LLM server or a 3d party API.

        :param str remote_id:  Job item ID
        :param dict details:  Job details
        :param DataSet dataset:  Dataset to run job for
        :return:
        """
        if not dataset:
            return cls.type

        return f"{cls.type}-{dataset.parameters.get('api_or_local', 'api')}"

    @classmethod
    def get_options(cls, parent_dataset=None, config=None) -> dict:
        # Check if 4CAT wide LLM server is available
        if config.get("llm.access", False) and config.get("llm.server", ""):
            shared_llm_name = config.get("llm.host_name", "4CAT LLM Server")
            shared_llm_models = {model: model_metadata.get("name") for model, model_metadata in config.get("llm.available_models", {}).items()}
            shared_llm_default = list(shared_llm_models.keys())[0] if shared_llm_models else ""
        else:
            shared_llm_name = False
            shared_llm_default = ""
            shared_llm_models = {}

        options = {
            "ethics_warning1": {
                "type": UserInput.OPTION_INFO,
                "help": "Always <strong>test your prompt</strong> on a sample of rows, for instance by first using the "
                "<strong>Random filter</strong> processor.",
            },
            "api_or_local": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Local or API",
                "options": {"api": "API", "local": "Local"}
                if not shared_llm_name
                else {"hosted": shared_llm_name, "api": "API", "local": "Local"},
                "default": "api" if not shared_llm_name else "hosted",
                "tooltip": "You can use 'local' models through Ollama and LM Studio as long as you have a valid "
                "and accessible URL through which the model can be reached.",
            },
            "api_model": {
                "type": UserInput.OPTION_CHOICE,
                "help": "API model",
                "options": LLMAdapter.get_model_options(config),
                "default": "none",
                "tooltip": "Select from the predefined model list or insert manually",
                "requires": "api_or_local==api",
            },
            "api_key": {
                "type": UserInput.OPTION_TEXT,
                "default": "",
                "help": "API key",
                "tooltip": "Create an API key on the LLM provider's website (e.g. https://admin.mistral.ai/organization"
                "/api-keys). Note that this often involves billing.",
                "requires": "api_or_local==api",
                "sensitive": True,
            },
            "api_custom_model_provider": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Model provider",
                "requires": "api_model==custom",
                "options": LLMAdapter.get_model_providers(config),
                "tooltip": "API provider. Currently limited to this list.",
            },
            "api_custom_model_id": {
                "type": UserInput.OPTION_TEXT,
                "help": "Model ID",
                "requires": "api_model==custom",
                "tooltip": "E.g. 'mistral-small-2503'. Check the API provider's documentation on what model ID to use. "
                "Fine-tuned models often require more info; OpenAI for instance requires the following "
                "format: ft:[modelname]:[org_id]:[custom_suffix]:",
                "default": "",
            },
            "local_info": {
                "type": UserInput.OPTION_INFO,
                "requires": "api_or_local==local",
                "help": "You can use local LLMs with LM Studio, Ollama, and vLLM. These applications need to be reachable by "
                "this 4CAT server, e.g. by running them on the same machine. For LM Studio and vLLM, "
                "use the Base URL to interface with any OpenAI-like API endpoint.",
            },
            "local_provider": {
                "type": UserInput.OPTION_CHOICE,
                "requires": "api_or_local==local",
                "options": {
                    "none": "",
                    "lmstudio": "LM Studio",
                    "ollama": "Ollama",
                    "vllm": "vLLM",
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
                "right (default: `http://localhost:1234/v1` or `http://host.docker.internal:1234/v1` in Docker). "
                "4CAT will use the top-most model you have loaded. ",
            },
            "ollama-info": {
                "type": UserInput.OPTION_INFO,
                "requires": "local_provider==ollama",
                "help": "Ollama is a simple command-line application that lets you interface with a range of open-"
                "source LLMs and that you can run as a local server. See [this link]"
                "(https://github.com/ollama/ollama/blob/main/README.md#quickstart) for instructions.",
            },
            "vllm-info": {
                "type": UserInput.OPTION_INFO,
                "requires": "local_provider==ollama",
                "help": "[vLLM](https://docs.vllm.ai/en/latest/getting_started/quickstart/) is a framework for Linux "
                "systems capable of fast inference with a single LLM. Communication is done through an "
                "OpenAI-like API endpoint. Just change the base URL below and insert an optional API key.",
            },
            "local_base_url": {
                "type": UserInput.OPTION_TEXT,
                "requires": "api_or_local==local",
                "default": "",
                "help": "Base URL",
                "tooltip": "[optional] Leaving this empty will use default values (`http://localhost:1234/v1` or `http://host.docker.internal:1234/v1` for LM "
                "Studio, `http://localhost:11434` or `http://host.docker.internal:11434` for Ollama, `http://localhost:8000` or `http://host.docker.internal:8000` for vLLM ).",
            },
            "lmstudio_api_key": {
                "type": UserInput.OPTION_TEXT,
                "default": "",
                "help": "LM Studio API key",
                "tooltip": "[optional] Uses `lm-studio` by default.",
                "requires": "local_provider==lmstudio",
                "sensitive": True,
            },
            "vllm_api_key": {
                "type": UserInput.OPTION_TEXT,
                "default": "",
                "help": "vLLM API key",
                "tooltip": "[optional] Empty by default.",
                "requires": "local_provider==vllm",
                "sensitive": True,
            },
            "ollama_model": {
                "type": UserInput.OPTION_TEXT,
                "requires": "local_provider==ollama",
                "default": "",
                "help": "Ollama model name",
                "tooltip": "[required] for example 'llama3.2'",
            },
            "hosted_llm_model": {
                "type": UserInput.OPTION_CHOICE,
                "help": "LLM model",
                "options": shared_llm_models,
                "default": shared_llm_default,
                "requires": "api_or_local==hosted",
            },
            "prompt_info": {
                "type": UserInput.OPTION_INFO,
                "help": "<strong>How to prompt</strong><br>"
                "Use `[brackets]` with column names to insert dataset items in the prompt. You "
                "can place column brackets in different parts of the prompt or use multiple column names within"
                ' a single column bracket to merge items.<br>Example 1: "Describe the topic '
                'of this social media post in max. 3 words: `[body, tags]`"<br>Example 2: '
                "\"Given the following hashtags: `[tags]`, answer whether they are 'related' or 'unrelated' "
                'to the following text: `[body]`"<br><strong>Prompting is a delicate art</strong>. See '
                "processor references on best prompting practices.<br>For predefined research prompts, see "
                "e.g. [Prompt Compass](https://github.com/ErikBorra/PromptCompass/blob/main/prompts.json#L136) "
                "or the [Anthropic Prompt Library](https://docs.anthropic.com/en/resources/prompt-library/"
                "library).",
            },
            "system_prompt": {
                "type": UserInput.OPTION_TEXT_LARGE,
                "help": "System prompt",
                "tooltip": "[optional] A system prompt can be used to give the LLM general instructions, for instance "
                "on the tone of the text. This processor may edit the system prompt to "
                "ensure correct output. System prompts are included in the results file.",
                "default": "",
            },
            "prompt": {
                "type": UserInput.OPTION_TEXT_LARGE,
                "help": "User prompt",
                "tooltip": "Use [brackets] with columns names.",
                "default": "",
            },
            "use_media": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Add images",
                "tooltip": "Add media URLs for multi-modal processing. Requires a model that supports vision.",
                "default": False,
            },
            "media_columns": {
                "type": UserInput.OPTION_TEXT,
                "help": "Columns with image URL(s)",
                "default": "",
                "inline": True,
                "tooltip": "Multiple columns can be selected.",
                "requires": "use_media==true",
            },
            "structured_output": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Output structured JSON",
                "tooltip": "Output in a JSON format instead of text. Note that your chosen model may not support "
                "structured output.",
                "default": False,
            },
            "json_schema_info": {
                "type": UserInput.OPTION_INFO,
                "help": "<strong>Insert a JSON Schema</strong> for structured outputs. These define the output that "
                "the LLM will adhere to. [See instructions and examples on how to write a JSON Schema]"
                "(https://json-schema.org/learn/miscellaneous-examples) and [OpenAI's documentation]"
                "(https://platform.openai.com/docs/guides/structured-outputs?api-mode=chat#supported-schemas).",
                "requires": "structured_output==true",
            },
            "json_schema": {
                "type": UserInput.OPTION_TEXT_LARGE,
                "help": "JSON schema",
                "tooltip": "[required] A JSON schema that the structured output will adhere to",
                "requires": "structured_output==true",
                "default": "",
            },
            "temperature": {
                "type": UserInput.OPTION_TEXT,
                "help": "Temperature",
                "default": 0.1,
                "coerce_type": float,
                "max": 2.0,
                "tooltip": "Temperature indicates how strict the model will gravitate towards the most "
                "probable next token. A score close to 0 returns more predictable "
                "outputs while a score close to 1 leads to more creative outputs. Not supported by all models.",
            },
            "truncate_input": {
                "type": UserInput.OPTION_TEXT,
                "help": "Max chars in input value",
                "default": 0,
                "coerce_type": int,
                "tooltip": "This value determines how many characters an inserted dataset value may have. 0 = unlimited.",
                "requires": "use_media==false",
            },
            "max_tokens": {
                "type": UserInput.OPTION_TEXT,
                "help": "Max output tokens",
                "default": 10000,
                "coerce_type": int,
                "tooltip": "As a rule of thumb, one token generally corresponds to ~4 characters of "
                "text for common English text. This includes tokens spent for reasoning.",
            },
            "batches": {
                "type": UserInput.OPTION_TEXT,
                "help": "Items per prompt",
                "coerce_type": int,
                "default": 1,
                "tooltip": "How many dataset items to insert into the prompt. These will be inserted as a list "
                "wherever the column brackets are used (e.g. '[body]').",
                "requires": "use_media==false",
            },
            "batch_info": {
                "type": UserInput.OPTION_INFO,
                "help": "<strong>Note on batching:</strong> Batching may increase speed but reduce accuracy. Models "
                "need to support structured output for batching. This processor uses JSON schemas to ensure "
                "symmetry between input and output lengths, but models may struggle to match input and output "
                "values. Describe the dataset values in plurals in your prompt when batching. If you use "
                "multiple column brackets in your prompt, rows with any empty values are skipped.",
                "requires": "use_media==false",
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
            "hide_think": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Hide reasoning",
                "default": False,
                "tooltip": "Some models include reasoning in their output, between <think></think> tags. This option "
                "removes this tag and its contents from the output.",
            },
            "limit": {
                "type": UserInput.OPTION_TEXT,
                "help": "Only annotate this many items, then stop",
                "default": 0,
                "coerce_type": int,
                "min": 0,
                "delegated": True,
            },
            "annotation_label": {
                "type": UserInput.OPTION_TEXT,
                "help": "Label for the annotations to add to the dataset",
                "default": "",
                "delegated": True,
            },
        }

        # Get the media columns for the select media columns option
        if parent_dataset and parent_dataset.get_columns():
            columns = parent_dataset.get_columns()
            options["media_columns"]["type"] = UserInput.OPTION_MULTI
            options["media_columns"]["options"] = {v: v for v in columns}

        return options

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Determine if processor is compatible with a dataset or processor

        :param module: Module to determine compatibility with
        """
        return module.get_extension() in ["csv", "ndjson"]

    def process(self):
        
        self.dataset.update_status("Validating settings")

        api_consent = self.parameters.get("consent", False)

        api_model = self.parameters.get("api_model")
        if api_model == "none":
            api_model = ""

        modal_location = self.parameters.get("api_or_local", "api") 
        hide_think = self.parameters.get("hide_think", False)

        # Add some friction if an API is used.
        if modal_location not in ["local", "hosted"] and not api_consent:
            self.dataset.finish_with_error("You must consent to your data being sent to the LLM provider first")
            return

        self.dataset.delete_parameter("consent")

        # Optional media columns for files
        media_columns = self.parameters.get("media_columns", []) if self.parameters.get("use_media") else []
        if type(media_columns) is str:
            media_columns = [media_columns]

        temperature = float(self.parameters.get("temperature", 0.1))
        temperature = min(max(temperature, 0), 2)
        max_input_len = int(self.parameters.get("truncate_input", 0))
        max_tokens = int(self.parameters.get("max_tokens"))
        system_prompt_base = self.parameters.get("system_prompt", "")
        limit = self.parameters.get("limit", 0)
        limit_reached = False

        # Set value for batch length in prompts
        batches = max(1, min(self.parameters.get("batches", 1), self.source_dataset.num_rows))
        use_batches = batches > 1
        if media_columns:  # no batching for media files
            use_batches = False
        if not use_batches:
            self.dataset.delete_parameter("batches")

        # Set all variables through which we can reach the LLM
        api_key = ""
        base_url = None
        client_kwargs = {}

        if modal_location == "local":
            provider = self.parameters.get("local_provider", "")
            base_url = self.parameters.get("local_base_url", "")

            if not provider:
                self.dataset.finish_with_error("Choose a local model provider")
                return

            if provider == "lmstudio":
                model = "lmstudio_model"
                if not base_url:
                    base_url = "http://127.0.0.1:1234/v1" if not self.config.get("USING_DOCKER", False) else "http://host.docker.internal:1234/v1"
                if not self.parameters.get("lmstudio_api_key"):
                    api_key = "lm-studio"
            elif provider == "ollama":
                model = self.parameters.get("ollama_model", "")
                if not model:
                    self.dataset.finish_with_error("You need to provide a model name for Ollama (e.g. 'llama3.2')")
                    return
                if not base_url:
                    base_url = "http://localhost:11434" if not self.config.get("USING_DOCKER", False) else "http://host.docker.internal:11434"
            elif provider == "vllm":
                model = "vllm_model"
                api_key = self.parameters.get("vllm_api_key", "")
                if not base_url:
                    base_url = "http://localhost:8000/v1"
            else:
                self.dataset.finish_with_error("Local provider not supported, choose either lmstudio or ollama")
                return

        elif modal_location == "hosted":
            base_url = self.config.get("llm.server", "")
            provider = self.config.get("llm.provider_type", "none").lower()
            api_key = self.config.get("llm.api_key", "")
            llm_auth_type = self.config.get("llm.auth_type", "")
            model = self.parameters.get("hosted_llm_model", "")
            if api_key and llm_auth_type:
                client_kwargs = {
                    "headers": {
                        llm_auth_type: api_key
                    }
                }
            if provider == "none" or not base_url:
                self.dataset.finish_with_error("4CAT LLM server not properly configured; contact the administrator")
                return
        else:
            if not api_model:
               self.dataset.finish_with_error("Select an API model or insert one manually")
               return
            # Models can be set manually already
            if api_model == "custom":
                model = self.parameters.get("api_custom_model_id", "")
                provider = self.parameters.get("api_custom_model_provider", "")
                if not model:
                    self.dataset.finish_with_error("You must provide a valid API model name/ID")
                    return
                if not provider:
                    self.dataset.finish_with_error("You must provide a valid API model provider")
                    return
            else:
                model_info = LLMAdapter.get_models(self.config).get(api_model, {})
                provider = model_info.get("provider")
                model = api_model

            api_key = self.parameters.get("api_key") or self.config.get(f"api.{provider}.api_key", "")
            if not api_key:
                self.dataset.finish_with_error("You need to provide a valid API key")
                return

        # Prompt validation
        base_prompt = self.parameters.get("prompt", "")
        if not base_prompt and not (system_prompt_base and media_columns):
            self.dataset.finish_with_error("You need to insert a valid user prompt")
            return
        self.dataset.update_status("Prompt: %s" % base_prompt)

        # Get column values in prompt. These can be one or multiple, and multiple within a bracket as well.
        columns_to_use = re.findall(r"\[.*?]", base_prompt)
        if not columns_to_use and not media_columns:
            self.dataset.finish_with_error(
                "You need to insert column name(s) in the user prompt within brackets (e.g. '[body]' "
                "or '[timestamp, author]')"
            )
            return
        columns_to_use = [c[1:-1].strip() for c in columns_to_use]  # Remove brackets

        # Check if there's no duplicate column brackets in the prompt
        all_columns = [c.strip() for col in columns_to_use for c in col.split(",")]  # Get all unique column names
        if len(set(all_columns)) != len(all_columns):
            duplicate_columns = set([c for c in all_columns if all_columns.count(c) > 1])
            self.dataset.finish_with_error(f"Only use unique column brackets. The current prompt "
                                           f"contains the following duplicate brackets: {', '.join(duplicate_columns)}.")
            return

        # Structured output
        structured_output = self.parameters.get("structured_output", False)
        json_schema = self.parameters.get("json_schema") if structured_output else None

        if structured_output:
            if not json_schema:
                self.dataset.finish_with_error("You need to provide a JSON schema for structured outputs.")
                return
            try:
                json_schema = json.loads(json_schema)
            except (TypeError, JSONDecodeError):
                self.dataset.finish_with_error("Your JSON schema is not valid JSON (copy/paste to jsonlint.com to check"
                                               " what's wrong).")
                return

        json_schema_original = json_schema or None  # We may manipulate the schema later, save a copy
        
        # Start LLM
        self.dataset.update_status("Connecting to LLM provider")
        self.dataset.log(f"Using LLM provider '{provider}' with model '{model}' at base URL '{base_url}'")
        try:
            llm = LLMAdapter(
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
                temperature=temperature,
                max_tokens=max_tokens,
                client_kwargs=client_kwargs
            )
        except Exception as e:
            self.dataset.finish_with_error(str(e))
            return

        # Setup annotation saving
        annotations = []
        save_annotations = self.parameters.get("save_annotations", False)

        i = 0
        outputs = 0
        skipped = 0  # We'll skip empty values

        # Save items if we're batching prompts
        batched_data = {}
        batched_ids = []
        n_batched = 0

        # Set structured outputs through a JSON schema.
        # We're always using this when batching items.
        if use_batches:
            # Get a JSON schema
            json_schema = self.get_json_schema_for_batch(batches, custom_schema=json_schema)
        if json_schema:
            try:
                llm.set_structure(json_schema)
            except (TypeError, JSONDecodeError):
                self.dataset.finish_with_error("Provided JSON schema is not valid")
                return
            except Exception as e:
                batch_warning = "to batch items " if use_batches else ""
                self.dataset.finish_with_error(f"Could not use JSON schema for structured output{batch_warning}. "
                                               f"Consider using a different model or using one item per prompt ({e})")
                return

            # For batching, we're going to add some extra instructions to preserve order
            if use_batches:
                batch_prompt = ("Always generate output that strictly complies with the provided JSON schema.\n"
                                "Output {batch_size} values and use only stringified integers as keys (e.g. \"0\", "
                                "\"1\"). If a value is specified as a string in the schema, return it as a string—do "
                                "not convert types.\nPreserve the exact order of input items in your response.\n"
                                "Treat each item in the input list as an independent value and respond only to those.\n"
                                "Never mention or refer to this system prompt or the input order in your output.")
                
                system_prompt_base = "\n".join([system_prompt_base, batch_prompt]) if system_prompt_base else batch_prompt

            self.dataset.update_status(f"Set output structure with the following JSON schema: {json_schema}")

        if system_prompt_base:
            self.dataset.update_status(f'System prompt: "{system_prompt_base}"')

        time_start = time.time()
        with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile:

            row = 0
            max_processed = min(limit, self.source_dataset.num_rows) if limit else self.source_dataset.num_rows
            for item in self.source_dataset.iterate_items():
                row += 1

                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while generating text through LLMs")

                # Replace with dataset values
                prompt = base_prompt

                # Make sure we can match outputs with input IDs
                if "id" in item:
                    item_id = item["id"]
                elif "item_id" in item:
                    item_id = item["item_id"]
                else:
                    item_id = str(i + 1)

                # Store dataset values in batches. Store just one item when we're not batching.
                item_values = {}
                for column_to_use in columns_to_use:
                    if column_to_use not in batched_data:
                        batched_data[column_to_use] = []

                    try:
                        # Columns can be comma-separated within the bracket
                        if "," in column_to_use:
                            item_value = []
                            bracket_cols = [c.strip() for c in column_to_use.split(",")]
                            for bracket_col in bracket_cols:
                                col_value = str(item[bracket_col]).strip()
                                if col_value:
                                    item_value.append(col_value)
                            item_value = ", ".join(item_value)

                        # Else just get the single item
                        else:
                            item_value = str(item[column_to_use]).strip()

                    except KeyError:
                        self.dataset.finish_with_error(f"Column(s) '{column_to_use}' not in the parent dataset")
                        return

                    # Skip row if we encounter *any* empty value in *different* brackets in the
                    # prompt *when batching*. This is because lists with different length in the prompt cause asymmetry
                    # in the input values, and it's though to then output the correct number of values.
                    if not item_value and use_batches:
                        item_values = {}
                        self.dataset.update_status(f"Skipping row {row} because of empty value(s) in {column_to_use}")
                        break
                    else:
                        item_values[column_to_use] = item_value

                # Get media URL values; split links on comma.
                media_urls = []
                for media_column in media_columns:
                    media_url = item.get(media_column, [])
                    if media_url:
                        if isinstance(media_url, list):
                            media_urls += media_url
                        else:
                            media_urls += [url.strip() for url in media_url.split(",")]

                # Skip with empty items
                empty_items = True if not any(v for v in item_values.values()) and columns_to_use else False
                if (empty_items and not media_urls) or (media_columns and not media_urls):
                    if item_values.keys():
                        missing_columns = andify(columns_to_use) if len(columns_to_use) > 1 else columns_to_use[0]
                        self.dataset.update_status(f"Skipping row {row} because of empty value(s) in {missing_columns}")
                    if media_columns and not media_urls:
                        missing_media_columns = andify(media_columns) if len(media_columns) > 1 else media_columns[0]
                        self.dataset.update_status(f"Skipping row {row} because of empty value(s) in {missing_media_columns}")
                    skipped += 1
                    # (but not if we've reached the end of the dataset; we want to process the last batch)
                    if row != self.source_dataset.num_rows:
                        continue
                # Else add the values to the batch
                else:
                    for item_column, item_value in item_values.items():
                        if max_input_len > 0:
                            item_value = item_value[:max_input_len]
                        batched_data[item_column].append(item_value)
                    n_batched += 1
                    batched_ids.append(item_id)  # Also store IDs, so we can match them to the output

                i += 1
                if limit and i >= max_processed:
                    limit_reached = True
                    
                # Generate text when there's something to process and when we've reached 1) the batch length (which can
                # be 1) or 2) the end of the dataset or 3) the custom limit.
                if n_batched and (n_batched % batches == 0 or row == self.source_dataset.num_rows or limit_reached):

                    # Insert dataset values into prompt. Insert as list for batched data, else just insert the value.
                    for column_to_use in columns_to_use:
                        prompt_values = batched_data[column_to_use]
                        prompt_values = prompt_values[0] if len(prompt_values) == 1 else f"```{json.dumps(prompt_values)}```"
                        prompt = prompt.replace(f"[{column_to_use}]", prompt_values)

                    # Possibly use a different batch size when we've reached the end of the dataset.
                    if row == self.source_dataset.num_rows and use_batches:
                        # Get a new JSON schema for a batch of different length at the end of the iteration
                        if n_batched != batches and json_schema:
                            json_schema = self.get_json_schema_for_batch(n_batched, custom_schema=json_schema_original)
                            # `llm` becomes a RunnableSequence when used, so we'll need to reset it here
                            llm = LLMAdapter(
                                provider=provider,
                                model=model,
                                api_key=api_key,
                                base_url=base_url,
                                temperature=temperature,
                                max_tokens=max_tokens,
                                client_kwargs=client_kwargs
                            )
                            llm.set_structure(json_schema)

                    # For batched_output, make sure the exact length of outputs is mentioned in the system prompt
                    if use_batches:
                        system_prompt = system_prompt_base.replace("{batch_size}", str(n_batched))
                    else:
                        system_prompt = system_prompt_base

                    batch_str = f" and {n_batched} items batched into the prompt" if use_batches else ""
                    self.dataset.update_status(f"Generating text at row {row:,}/"
                                               f"{max_processed:,} with {model}{batch_str}")
                    # Now finally generate some text!
                    try:
                        response = llm.generate_text(
                            prompt,
                            system_prompt=system_prompt,
                            temperature=temperature,
                            files=media_urls
                        )

                    # Catch 404 errors with media URLs, we simply skip these
                    except requests.exceptions.HTTPError as e:
                        if e.response.status_code == 404 and media_urls:
                            self.dataset.log(f"Skipping row {row} because of media URL is not reachable, ({e})")
                            skipped += 1
                            continue
                        else:
                            self.dataset.finish_with_error(f"{e}")
                            return
                    # Broad exception, but necessary with all the different LLM providers and options...
                    except Exception as e:
                        self.dataset.finish_with_error(f"{e}")
                        return

                    # Set model name from the response for more details
                    if hasattr(response, "response_metadata"):
                        model = response.response_metadata.get("model_name", model)
                        if "models/" in model:
                            model = model.replace("models/", "")

                    if not response:
                        structured_warning = " with your specified JSON schema" if structured_output else ""
                        self.dataset.finish_with_error(f"{model} could not return text{structured_warning}. Consider "
                                                       f"editing your prompt or changing settings.")
                        return

                    # Always parse JSON outputs in the case of batches.
                    if use_batches or structured_output:
                        if isinstance(response, str):
                            response = json.loads(response)
                        
                        # Check whether input/output value lengths match
                        if use_batches:
                            output = self.parse_batched_response(response)

                            if len(output) != n_batched:
                                self.dataset.update_status(f"Output did not result in {n_batched} item(s).\nInput:\n"
                                                           f"{prompt}\nOutput:\n{response}")
                                self.dataset.finish_with_error("Model could not output as many values as the batch. See log "
                                                               "for incorrect output. Try lowering the batch size, "
                                                               "editing the prompt, or using a different model.")
                                return
                        else:
                            output = [response]

                        # Also validate whether the JSON schema and the output match
                        try:
                            jsonschema.validate(instance=response, schema=json_schema)
                        except (ValidationError, SchemaError) as e:
                            self.dataset.finish_with_error(f"Invalid JSON schema and/or LLM output: `{e}`")
                            return

                    # Else we'll just store the output in a list
                    else:

                        output = response.content

                        if not isinstance(output, list):
                            output = [output]

                        # More cleaning
                        # Magistral gives back an annoying nested dict with 'thinking' and 'text', flatten it
                        if len(output) > 0 and isinstance(output[0], dict) and output[0].get("type") == "thinking":
                            output_flat = {"thinking": "", "text": []}
                            for output_part in output:
                                if output_part.get("type") == "thinking":
                                    output_flat["thinking"] += "\n".join([think["text"] for think in output_part["thinking"]])
                                else:
                                    output_flat["text"].append(output_part.get("text", ""))
                            output_flat["text"] = "\n".join(output_flat["text"])
                            output = [output_flat]

                    for n, output_item in enumerate(output):

                        # Retrieve the input values used
                        if use_batches:
                            input_value = [v[n] for v in batched_data.values()]
                        else:
                            input_value = [v[0] for v in batched_data.values()]

                        time_created = int(time.time())

                        # remove reasoning if so desired
                        if hide_think:
                            if isinstance(output_item, str):
                                output_item = re.sub(r"<think>.*</think>", "", output_item, flags=re.DOTALL).strip()
                            elif isinstance(output_item, dict):
                                if "thinking" in output_item:
                                    del output_item["thinking"]

                        result = {
                            "id": batched_ids[n],
                            "output": output_item,
                            "input_value": input_value,
                            "prompt": prompt if not use_batches else base_prompt,  # Insert dataset values if not batching
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                            "model": model,
                            "time_created": datetime.fromtimestamp(time_created).strftime("%Y-%m-%d %H:%M:%S"),
                            "time_created_utc": time_created,
                            "batch_number": n + 1 if use_batches else "",
                            "system_prompt": system_prompt,
                        }
                        outfile.write(json.dumps(result) + "\n")
                        outputs += 1

                        if save_annotations:
                            # Save annotations for every value produced by the LLM, in case of structured output.
                            # Else this will just save one string.
                            if isinstance(output_item, dict):
                                annotation_output = flatten_dict({model: output_item})
                            elif self.parameters.get("annotation_label"):
                                annotation_output = {self.parameters.get("annotation_label"): output_item}
                            else:
                                annotation_output = {model + "_output": output_item}

                            for output_key, output_value in annotation_output.items():
                                annotation = {
                                    "label": output_key,
                                    "item_id": batched_ids[n],
                                    "value": remove_nuls(output_value),
                                    "type": "text",
                                }

                                annotations.append(annotation)

                    # Remove batched data and store what row we've left off
                    batched_ids = []
                    batched_data = {}
                    n_batched = 0

                    # Rate limits for different providers
                    if provider == "mistral":
                        time.sleep(1)

                # Write annotations in batches
                if (i % 1000 == 0 and annotations) or limit_reached:
                    self.save_annotations(annotations)
                    annotations = []

                self.dataset.update_progress(row / max_processed)
                if limit_reached:
                    break

        outfile.close()

        if not outputs:
            self.dataset.finish_with_error("Did not generate any output")
            return

        # Write leftover annotations
        if annotations:
            self.save_annotations(annotations)

        # Final outputs
        time_end = time.time()
        time_progressed = str(timedelta(seconds=int(time_end - time_start)))
        skipped_str = "" if not skipped else f" Skipped {skipped} rows because of empty values."
        self.dataset.update_status(f"Finished, {model} generated text in {time_progressed}.{skipped_str}", is_final=True)
        self.dataset.finish(i)

    @staticmethod
    def get_json_schema_for_batch(batch_size: int, custom_schema: dict = None) -> dict:
        """
        Generates a JSON schema for an array of exactly `batch_size` items.

        Each item in the array will conform to the given `item_schema`.

        Parameters:
        - batch_size (int): Number of items in the array.
        - custom_schema (dict): Schema of a single item in the array.

        Returns:
        - dict: A JSON schema dict.

        """
        json_schema = {
            "title": "batched_output_values",
            "description": "Objects for all nth values found in lists in the user prompt.",
            "type": "object",
            "properties": {}
        }
        for batch in range(batch_size):
            # 1st, 2nd, 3rd, 4th...
            batch_str = nthify(batch + 1)
            # Add nth item to schema
            json_schema["properties"][str(batch)] = {
                "description": f"The output for every {batch_str} item in lists found in the user prompt",
                "type": "string" if not custom_schema else "object"
            }
            if custom_schema:
                json_schema["properties"][str(batch)] = custom_schema

        json_schema["required"] = [str(i) for i in range(batch_size)]

        return json_schema

    @staticmethod
    def parse_batched_response(response) -> list:
        """
        Parse the batched LLM output and return all values as a list.
        """

        parsed_response = response.content if not isinstance(response, dict) else response

        # Cast to string
        if isinstance(parsed_response, str):
            try:
                parsed_response = json.loads(parsed_response)
            except JSONDecodeError:
                pass

        if isinstance(parsed_response, list) and len(parsed_response) == 1:
            parsed_response = parsed_response[0]

        if isinstance(parsed_response, dict):
            # Output is often with a key 'results'
            parsed_response = parsed_response.get("results", parsed_response)

            # Sort by integer keys (e.g. {"1": "hello", "0", "yes"}), if possible.
            # Some models don't give this back in order.
            integer_keys = all(k.isdigit() for k in parsed_response.keys())
            if integer_keys:
                parsed_response = dict(sorted(parsed_response.items(), key=lambda item: int(item[0])))

        return list(parsed_response.values())

    @staticmethod
    def map_item(item):

        # Output could be a JSON via structured output
        # Every nested key in this JSON will become its own flattened key if this is the case.
        output = flatten_dict({"output": item["output"]}) if isinstance(item["output"], dict) else {"output": item["output"]}

        return MappedItem({
            "id": item["id"],
            **output,
            "input_value": ",".join(item["input_value"]),
            "prompt": item["prompt"],
            "temperature": item["temperature"],
            "max_tokens": item["max_tokens"],
            "model": item["model"],
            "time_created": item["time_created"],
            "time_created_utc": item["time_created_utc"],
            "batch_number": item["batch_number"],
            "system_prompt": item["system_prompt"]
        })
