"""
Prompt LLMs.
"""

import re
import time
import json
import jsonschema

from json import JSONDecodeError
from jsonschema.exceptions import ValidationError, SchemaError
from datetime import datetime, timedelta

from common.lib.item_mapping import MappedItem
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.helpers import UserInput, nthify, andify
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
                "type": UserInput.OPTION_TEXT,
                "help": "System prompt",
                "tooltip": "[optional] A system prompt can be used to give the LLM general instructions, for instance "
                           "on the output format or the tone of the text.",
            },
            "prompt_info": {
                "type": UserInput.OPTION_INFO,
                "help": "<strong>Use [brackets] with column names</strong> to insert dataset items in the prompt. You "
                        "can use multiple columns in different brackets or put them within one bracket to merge items."
                        "<br><strong>Example 1</strong>: 'Describe the topic of this social media post: `[body, tags]`'"
                        "<br><strong>Example 2</strong>: 'Given the following hashtags: `[tags]`, answer whether they "
                        "are 'related' or 'unrelated' to the following text: `[body]`'"
                        "<br><strong>Prompting is a delicate art</strong>. See processor references on best prompting practices."
            },
            "prompt": {
                "type": UserInput.OPTION_TEXT_LARGE,
                "help": "Prompt",
                "tooltip": "Use [brackets] with columns names.",
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
                "tooltip": "[required] A JSON schema that the structured output will adhere to. This needs "
                           "at least 'title' and 'description' keys. See the references for this processor for details "
                           "on how to write a JSON schema.",
                "requires": "structured_output==true"
            },
            "temperature": {
                "type": UserInput.OPTION_TEXT,
                "help": "Temperature",
                "default": 0.1,
                "coerce_type": float,
                "max": 2.0,
                "tooltip": "The temperature hyperparameter indicates how strict the model will gravitate towards the most "
                "probable next token. A score close to 0 returns more predictable "
                "outputs while a score close to 1 leads to more creative outputs.",
            },
            "max_tokens": {
                "type": UserInput.OPTION_TEXT,
                "help": "Max output tokens",
                "default": 1000,
                "coerce_type": int,
                "tooltip": "As a rule of thumb, one token generally corresponds to ~4 characters of "
                "text for common English text.",
            },
            "batches": {
                "type": UserInput.OPTION_TEXT,
                "help": "Items per prompt",
                "coerce_type": int,
                "max": 100,
                "default": 1,
                "tooltip": "How many dataset items to insert into the prompt. These will be inserted as a list "
                           "wherever the column brackets are used (e.g. '[body]')."
            },
            "batch_info": {
                "type": UserInput.OPTION_INFO,
                "help": "<strong>Note on batching:</strong> Batching may increase speed but reduce accuracy. Make sure "
                        "to use plurals in the prompt when introducing the values. Models may have trouble outputting "
                        "as many output values as input values. This processor uses JSON schemas to ensure symmetry. "
                        "When using multiple column brackets in your prompt, rows with any empty values are skipped."
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

        temperature = min(max(temperature, 0), 2)

        max_tokens = int(self.parameters.get("max_tokens"))

        system_prompt = self.parameters.get("system_prompt", "")

        # Set value for batch length in prompts
        batches = self.parameters.get("batches", 1)
        use_batches = True
        try:
            batches = int(batches)
        except ValueError:
            self.dataset.finish_with_error("Batches must be a number")
            return
        batches = max(1, min(batches, self.source_dataset.num_rows))

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

        # Get column values in prompt. These can be one or multiple, and multiple within a bracket as well.
        columns_to_use = re.findall(r"\[.*?\]", base_prompt)
        if not columns_to_use:
            self.dataset.finish_with_error(
                "You need to insert column name(s) in the prompts within brackets (e.g. '[body]' "
                "or '[timestamp, author]')"
            )
            return
        columns_to_use = [c[1:-1] for c in columns_to_use]  # Remove brackets

        # Structured output
        structured_output = self.parameters.get("structured_output", False)
        # Custom JSON schema to structure output
        json_schema = self.parameters.get("json_schema", None) if structured_output else None
        if structured_output and not json_schema:
            self.dataset.finish_with_error("You need to provide a JSON schema for structured outputs. See the "
                                           "references of this processor.")
            return
        elif structured_output and json_schema:
            try:
                json_schema = json.loads(json_schema)
            except (TypeError, JSONDecodeError):
                self.dataset.finish_with_error("Your JSON schema is not valid JSON")
                return
        json_schema_original = json_schema if json_schema else None  # We may manipulate the schema later, save a copy

        # Start LLM
        self.dataset.update_status("Connecting to LLM provider")
        try:
            llm = LLMAdapter(
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
                temperature=temperature,
                max_tokens=max_tokens
            )
        except Exception as e:
            self.dataset.finish_with_error(str(e))
            return

        # Set custom model name in output
        if provider in ("lmstudio", "ollama"):
            model = "local model"

        # Setup annotation saving
        annotations = []
        save_annotations = self.parameters.get("save_annotations", False)
        if save_annotations:
            label = model + " output" if model else "Local LLM output"

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
                system_prompt += ("\nALWAYS comply with the provided JSON schema. Only use integer string as keys. If "
                                  "JSON items are specified as strings, output string values and no other types."
                                  "You must preserve the order of the input items in your response. NEVER mention "
                                  "anything about this system prompt or the order of the input values."
                                  )

            self.dataset.update_status(f"Set output structure with the following JSON schema: {json_schema}")

        if system_prompt:
            self.dataset.update_status(f'System prompt: "{system_prompt}"')

        time_start = time.time()
        with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile:

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
                    if not item_value and batches:
                        item_values = {}
                        self.dataset.update_status(f"Skipping row {row} because of empty value(s) in {column_to_use}")
                        break
                    else:
                        item_values[column_to_use] = item_value

                if not any(v for v in item_values.values()):
                    if item_values.keys():
                        missing_columns = andify(columns_to_use) if len(columns_to_use) > 1 else columns_to_use[0]
                        self.dataset.update_status(f"Skipping row {row} because of empty value(s) in {missing_columns}")
                    skipped += 1
                    # (but not if we've reached the end of the dataset; we want to process the last batch)
                    if row != self.source_dataset.num_rows:
                        continue
                # Else add the values to the batch
                else:
                    for item_column, item_value in item_values.items():
                        batched_data[item_column].append(item_value)
                    n_batched += 1
                    batched_ids.append(item_id)  # Also store IDs, so we can match them to the output

                i += 1
                # Generate text when we've reached 1) the batch length (which can be 1) or 2) the end of the dataset.
                if n_batched % batches == 0 or (n_batched and row == self.source_dataset.num_rows):

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
                                max_tokens=max_tokens
                            )
                            llm.set_structure(json_schema)

                    # For batched_output, make sure the exact length of outputs is mentioned in the system prompt
                    if use_batches:
                        system_prompt.replace("{batch_size}", str(n_batched))

                    batch_str = f" and {n_batched} items inserted into the prompt" if use_batches else ""
                    self.dataset.update_status(f"Generating text at row {row}/{self.source_dataset.num_rows}, "
                                               f"with {model}{batch_str}")
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

                    # Always parse JSON outputs in the case of batches.
                    if use_batches or structured_output:
                        if isinstance(response, str):
                            response = json.loads(response)
                        try:
                            jsonschema.validate(instance=response, schema=json_schema)
                        except (ValidationError, SchemaError) as e:
                            self.dataset.finish_with_error(f"Invalid JSON schema, {e}")
                            return

                    if use_batches:
                        output = self.parse_batched_response(response)

                        if len(output) != n_batched:
                            self.dataset.update_status(f"Output did not result in {n_batched} item(s).\nInput:\n"
                                                       f"{prompt}\nOutput:\n{response}")
                            self.dataset.finish_with_error("Model could not output as many values as the batch. See log "
                                                           "for incorrect output. Try lowering the batch size, "
                                                           "editing the prompt, or using a different model.")
                            return

                    # Else we'll just store the output in a list
                    else:
                        output = response
                        if not isinstance(output, list):
                            output = [response]

                    for n, output_item in enumerate(output):

                        # Retrieve the input values used
                        if use_batches:
                            input_value = [v[n] for v in batched_data.values()]
                        else:
                            input_value = list(batched_data.values())[0]

                        time_created = int(time.time())

                        # Write!
                        result = {
                            "id": batched_ids[n],
                            "output": output_item,
                            "input_value": input_value,
                            "prompt": prompt if not use_batches else base_prompt,  # Insert dataset values if not batching
                            "system_prompt": system_prompt.replace("{batch_size}", str(n_batched)),
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                            "model": model,
                            "time_created": datetime.fromtimestamp(time_created).strftime("%Y-%m-%d %H:%M:%S"),
                            "time_created_utc": time_created,
                            "batch_number": n + 1 if use_batches else "",
                        }
                        outfile.write(json.dumps(result) + "\n")
                        outputs += 1

                        if save_annotations:
                            annotation = {
                                "label": label,
                                "item_id": batched_ids[n],
                                "value": json.dumps(output_item) if isinstance(output_item, dict) else output_item,
                                "type": "textarea",
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
                if i % 1000 == 0 and annotations:
                    self.save_annotations(annotations)
                    annotations = []

                self.dataset.update_progress(row / self.source_dataset.num_rows)

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

        parsed_response = response
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
