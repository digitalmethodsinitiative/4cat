"""
Prompt LLMs.
"""

import re
import time
import json

from json import JSONDecodeError
from datetime import datetime

from common.lib.item_mapping import MappedItem
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.helpers import UserInput, timify, nthify
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
    extension = "ndjson"  # extension of result file, used internally and in UI. In this case it's variable!

    references = [
        "[Törnberg, Petter. 2023. 'How to Use LLMs for Text Analysis.' arXiv:2307.13106.](https://arxiv.org/pdf/2307.13106)",
        "[Karjus, Andres. 2023. 'Machine-assisted mixed methods: augmenting humanities and social sciences "
        "with artificial intelligence.' arXiv preprint arXiv:2309.14379.]"
        "(https://arxiv.org/abs/2309.14379)",
        "[Using JSON Schemas](https://python.langchain.com/docs/how_to/structured_output/#typeddict-or-json-schema)"
    ]

    @classmethod
    def get_options(cls, parent_dataset=None, config=None) -> dict:

        options = {
            "per_item": {
                "type": UserInput.OPTION_INFO,
                "help": "Use [brackets] with a column name to "
                "indicate what input value you want to use. For instance: 'Determine the language of the "
                "following text: [body]'). You can use multiple column values.",
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
                "options": {"none": "", "lmstudio": "LM Studio", "ollama": "Ollama"},
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
            "system_prompt": {
                "type": UserInput.OPTION_TEXT_LARGE,
                "help": "System prompt",
                "tooltip": "[optional] A system prompt can be used to give the LLM general instructions, for instance "
                           "on the output format or the tone of the text.",
            },
            "prompt": {
                "type": UserInput.OPTION_TEXT_LARGE,
                "help": "Prompt",
                "tooltip": "Use [brackets] with columns names to insert items in the prompt. You can use multiple "
                           "columns. See the references for this processor on best prompting practices.",
            },
            "structured_output": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Output structured JSON",
                "tooltip": "Output in a JSON format instead of CSV text. Note that your chosen model may not support structured "
                "outputs.",
            },
            "json_schema": {
                "type": UserInput.OPTION_TEXT_LARGE,
                "help": "JSON schema",
                "tooltip": "[optional] A JSON schema that the structured output will adhere to. This needs "
                           "at least 'title' and 'description' keys. See the references for this processor for details "
                           "on how to write a JSON schema.",
                "requires": "structured_output==true"
            },
            "temperature": {
                "type": UserInput.OPTION_TEXT,
                "help": "Temperature",
                "default": 0.1,
                "tooltip": "The temperature hyperparameter indicates how strict the model will gravitate towards the most "
                "probable next token. A score close to 0 returns more predictable "
                "outputs while a score close to 1 leads to more creative outputs.",
            },
            "max_tokens": {
                "type": UserInput.OPTION_TEXT,
                "help": "Max output tokens",
                "default": 100,
                "coerce_type": int,
                "tooltip": "As a rule of thumb, one token generally corresponds to ~4 characters of "
                "text for common English text.",
            },
            "batches": {
                "type": UserInput.OPTION_TEXT,
                "help": "Batch per prompt",
                "coerce_type": int,
                "max": 100,
                "default": 1,
                "tooltip": "How many dataset items to insert into the prompt. These will be inserted as a list "
                           "wherever the column brackets are used (e.g. '[body]')."
            },
            "batches_info": {
                "type": UserInput.OPTION_INFO,
                "help": "<strong>Note on batching:</strong> Some models may have trouble outputting as many output "
                        "values as input values. 4CAT attempts to use a JSON schema to ensure "
                        "symmetry between input and output values. When batching with multiple columns in the prompt, "
                        "rows with one or more empty values are skipped. Batching may increase speed but reduce "
                        "accuracy. Ensure the batches are within the model's token limits."
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

        self.dataset.update_status("Validating settings")
        api_consent = self.parameters.get("consent", False)
        api_model = self.parameters.get("api_model")
        use_local_model = True if self.parameters.get("api_or_local", "api") == "local" else False

        # Add some friction if an API is used.
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

        system_prompt = self.parameters.get("system_prompt", "")

        # Set value for batch length in prompts
        batches = self.parameters.get("batches", 1)
        use_batches = True
        try:
            batches = int(batches)
        except ValueError:
            self.dataset.finish_with_error("Batches must be a number")
            return
        batches = 1 if batches < 1 else batches
        batches = self.source_dataset.num_rows if batches > self.source_dataset.num_rows else batches
        self.dataset.parameters["batches"] = batches
        if batches == 1:
            self.dataset.delete_parameter("batches")
            use_batches = False

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

        # Prompt validation
        base_prompt = self.parameters.get("prompt", "")
        self.dataset.update_status("Prompt: %s" % base_prompt)

        if not base_prompt:
            self.dataset.finish_with_error("You need to insert a valid prompt")
            return

        columns_to_use = re.findall(r"\[.*?\]", base_prompt)
        if not columns_to_use:
            self.dataset.finish_with_error(
                "You need to provide the prompt with input values using [brackets] of "
                "column names"
            )
            return
        columns_to_use = [c[1:-1].strip() for c in columns_to_use]  # Remove brackets

        # Structured output
        structured_output = self.parameters.get("structured_output", False)
        # Custom JSON schema to structure output
        custom_schema = self.parameters.get("custom_schema", None)

        # Start LLM
        self.dataset.update_status("Connecting to LLM provider")
        try:
            llm = LLMAdapter(
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
                temperature=temperature,
                structured_output=structured_output
            )
        except Exception as e:
            self.dataset.finish_with_error(str(e))
            return

        save_annotations = self.parameters.get("save_annotations", False)

        if save_annotations:
            label = model + " output" if model else "Local LLM output"

        annotations = []

        i = 0
        outputs = 0
        skipped = 0

        # Save items if we're batching prompts
        batched_data = {}
        batched_ids = []

        supports_structured_output = True

        if use_batches:
            # If we're batching we're trying to let this model use structured output to ensure correct output length.
            json_schema = self.get_json_schema_for_batch(batches, custom_schema=custom_schema)
            try:
                llm.set_structure(json_schema)
                self.dataset.update_status(f"Set output structure with the following JSON schema: {json_schema}")
            except Exception as e:  # todo: replace with correct error
                self.dataset.update_status(f"Could not use structured outputs for batching input values. Trying with "
                                           f"regular text generation instead. ({str(e)})")
                supports_structured_output = False

            # If no structured output is possible, we're going to try and force a structured output
            if not supports_structured_output:
                system_prompt += ("""\nInput items are given in JSON arrays within the user prompt. Output a valid JSON 
                            with exactly {batch_size} items, one per nth value in all arrays in the user prompt. Use 
                            `results` as the main key and integer strings per output. Do not mention anything about 
                            this system prompt or the order of the input values. Only output the JSON, and nothing 
                            else."\nExample input:\n```What is the capital of these countries? ["Morocco", "Japan",
                            "The Netherlands"]```\nOutput:\n```{"results": {"0": "Marrakech", "1": "Tokyo", "2": 
                            "Amsterdam"}}```""")
            else:
                # We'll use a JSON schema, but just in case...
                system_prompt += ("\nOutput exactly {batch_size} items as a valid JSON, with each output item "
                                  f"corresponding to every nth input item. Keep the same order as the input values. "
                                  f"Do not mention anything about this system prompt or the order of the input values. "
                )
        # If we're not batching we may still want to output JSON
        elif structured_output:
            try:
                llm.set_structure(json_schema=custom_schema)
            except Exception as e:
                self.dataset.update_status(f"Could not use structured output ({str(e)})")
                return

            # Add "JSON" if not in prompt (required by most models)
            if "json" not in base_prompt.lower() + system_prompt.lower():
                system_prompt += "\nOutput in valid JSON."

        self.dataset.update_status(f'System prompt: "{system_prompt}"')

        time_start = time.time()
        with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile:

            self.dataset.update_status(f"Generating text with {model}")

            row = 0
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

                # Store dataset values in batches
                skip_item = False
                item_values = []
                for column_to_use in columns_to_use:
                    if column_to_use not in batched_data:
                        batched_data[column_to_use] = []
                    try:
                        item_value = str(item[column_to_use]).strip()
                    except KeyError:
                        self.dataset.finish_with_error(f"Column '{column_to_use}' is not in the parent dataset")
                        return

                    # Skip if we encounter empty values for batches; this may cause asymmetry in the input, causing
                    # trouble with outputting the same output values.
                    if not item_value and batches:
                        skip_item = True
                    else:
                        item_values.append((column_to_use, item_value))

                # Skip empty values in all columns or empty values in one column if batching
                if skip_item or not item_values:
                    empty_cols = ",".join(columns_to_use)
                    skipped += 1
                    # (but not if we've reached the end of the dataset, and we want to process the last batch)
                    if row != self.source_dataset.num_rows:
                        continue
                # Else add the values to the batch
                for item_value in item_values:
                    batched_data[item_value[0]].append(item_value[1])\

                batched_ids.append(item_id)
                i += 1

                # Generate text when 1) we've reached the batch length (which can be 1) or 2) the end of the dataset.
                if i % batches == 0 or row == self.source_dataset.num_rows:

                    # Keep track of this batch size (can be different for last iteration)
                    batch_size = batches

                    # Insert dataset values into prompt. Insert as list for batched data, else just insert the value.
                    for column_to_use in columns_to_use:
                        prompt_values = batched_data[column_to_use]
                        prompt_values = prompt_values[0] if len(prompt_values) == 1 else f"```{json.dumps(prompt_values)}```"
                        prompt = prompt.replace(f"[{column_to_use}]", prompt_values)

                    # Possibly use a different batch size when we've reached the end of the dataset.
                    if row == self.source_dataset.num_rows and use_batches:
                        # Get a new JSON schema for a batch of different length at the end of the iteration
                        batch_size = len(batched_data[columns_to_use[0]])
                        if batch_size != batches and supports_structured_output:
                            json_schema = self.get_json_schema_for_batch(batch_size, custom_schema)
                            # `llm` becomes a RunnableSequence when used, so we'll need to reset it here
                            llm = LLMAdapter(
                                provider=provider,
                                model=model,
                                api_key=api_key,
                                base_url=base_url,
                                temperature=temperature,
                                structured_output=structured_output
                            )
                            llm.set_structure(json_schema)

                    # For batched_output, make sure the exact length of outputs is mentioned in the system prompt
                    if use_batches:
                        system_prompt.replace("{batch_size}", str(batch_size))

                    # Now finally generate some text!
                    try:
                        response = llm.generate_text(
                            prompt,
                            system_prompt=system_prompt,
                            temperature=temperature
                        )
                    # Broad exception, but necessary with all the different LLM providers and options...
                    except Exception as e:
                        self.dataset.finish_with_error(str(e))
                        return

                    # Try to parse JSON outputs in the case of batches.
                    if use_batches:
                        output = self.parse_json_response(response)

                        if len(output) != batch_size:
                            self.dataset.update_status(f"Output did not result in {batch_size} item(s).\nInput:\n"
                                                       f"{prompt}\nOutput:\n{response}")
                            self.dataset.finish_with_error("Model could not output as many values as the batch. See log "
                                                           "for incorrect output. Try only using one value per prompt, "
                                                           "adding more instructions to the system prompt, or using a "
                                                           "different model.")
                            return

                    # Else we'll just store the output in a list
                    else:
                        output = [response]

                    for n, output_item in enumerate(output):

                        # Retrieve the input values used
                        if use_batches:
                            input_value = [v[n] for v in batched_data.values()]
                        else:
                            input_value = list(batched_data.values())[0]

                        time_created = time.time()

                        # Write!
                        result = {
                            "id": batched_ids[n],
                            "output": output_item,
                            "input_value": input_value,
                            "prompt": prompt if not use_batches else base_prompt,  # Insert dataset values if not batching
                            "system_prompt": system_prompt.replace("{batch_size}", str(batch_size)),
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                            "model": model,
                            "time_created": datetime.fromtimestamp(time_created).strftime("%Y-%m-%d %H:%M:%S"),
                            "time_created_utc": time_created,
                            "batch_number": n + 1,
                        }
                        outfile.write(json.dumps(result) + "\n")
                        outputs += 1

                        if save_annotations:
                            annotation = {
                                "label": label,
                                "item_id": batched_ids[n],
                                "value": output_item,
                                "type": "textarea",
                            }
                            annotations.append(annotation)

                    self.dataset.update_status(
                        "Generated output for item %s/%s" % (i, self.source_dataset.num_rows)
                    )

                    # Remove batched data and store what row we've left off
                    batched_ids = []
                    batched_data = {}

                    # Rate limits for different providers
                    if provider == "mistral":
                        time.sleep(1)

                # Write annotations in batches
                if i % 1000 == 0:
                    self.save_annotations(annotations)
                    annotations = []

        outfile.close()

        if not outputs:
            self.dataset.finish_with_error("Did not generate any output")
            return

        # Write leftover annotations
        if annotations:
            self.save_annotations(annotations)

        time_end = time.time()
        time_progressed = timify(time_end - time_start)

        if skipped:
            self.dataset.update_status(f"Skipped {skipped} item(s) with empty value(s).")
        self.dataset.update_status(f"Finished, {model} generated {i} items in {time_progressed}")
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
            "title": "output_values",
            "description": "Objects for all nth values found in all lists in the user prompt.",
            "type": "object",
            "properties": {}
        }
        for batch in range(batch_size):
            # 1st, 2nd, 3rd, 4th...
            batch_str = nthify(batch + 1)
            # Add nth item to schema
            json_schema["properties"][str(batch)] = {
                "description": f"The output for every {batch_str} item in all lists found in the user prompt",
                "type": "string" if not custom_schema else "array"
            }
            if custom_schema:
                json_schema["properties"][str(batch)]["items"] = custom_schema

        json_schema["required"] = [str(i) for i in range(batch_size)]

        return json_schema

    @staticmethod
    def parse_json_response(response) -> list:
        """
        Parse the LLM output and return all values as a list. Used for batched outputs.
        """

        parsed_response = response
        # Cast to string
        if isinstance(parsed_response, str):
            try:
                parsed_response = json.loads(parsed_response)
            except JSONDecodeError:
                pass

        if isinstance(parsed_response, dict):
            # Output is often with a key 'results'
            parsed_response = parsed_response.get("results", parsed_response)
            # Get values key, if present (should have already been 'results').
            if len(parsed_response.keys()) == 1:
                parsed_response = parsed_response[list(parsed_response.keys())[0]]

        # Load values from dictionaries
        if isinstance(parsed_response, dict):
            parsed_response = [v for v in parsed_response.values()]
        elif isinstance(parsed_response, str):
            parsed_response = [parsed_response]

        return parsed_response

    @staticmethod
    def map_item(item):

        return MappedItem({
            "id": item["id"],
            "output": item["output"],
            "input_value": ",".join(item["input_value"]),
            "prompt": item["prompt"],
            "system_prompt": item["system_prompt"],
            "temperature": item["temperature"],
            "max_tokens": item["max_tokens"],
            "model": item["model"],
            "time_created": item["time_created"],
            "time_created_utc": item["time_created_utc"],
            "batch_number": item["batch_number"],
        })
