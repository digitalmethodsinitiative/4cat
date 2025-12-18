"""
Use a prompt from a preset list
"""
from backend.lib.preset import ProcessorPreset
from common.lib.helpers import UserInput
from common.lib.llm import LLMAdapter

from common.lib.exceptions import (
    QueryParametersException,
    QueryNeedsExplicitConfirmationException,
)

from processors.machine_learning.llm_prompter import LLMPrompter

import json

class PromptCompassRunner(ProcessorPreset):
    """
    Run processor pipeline to feed prompts to LLM Prompter
    """
    type = "preset-prompt-compass"  # job type ID
    category = "Machine learning"  # category
    title = "PromptCompass: Test task-specific prompts"  # title displayed in UI
    description = ("Choose prompts used in other LLM-based research to test on this dataset. Outcomes are added to the "
                   "original dataset as a new column.")
    extension = "ndjson"

    references = [
	    "This processor is an implementation of the stand-alone tool [PromptCompass](https://github.com/ErikBorra/PromptCompass) by Erik Borra.",
	    "See the processor options for references to the sources of each prompt in the library."
    ]

    @staticmethod
    def get_prompt_library(config):
        """
        Get prompt library from file

        :return list:  List of prompts and metadata
        """
        prompt_library_file = config.get("PATH_ROOT").joinpath("common/assets/prompt_library.json")
        if not prompt_library_file.exists():
            return []
        
        with prompt_library_file.open(encoding="utf-8") as infile:
            prompt_library = json.load(infile)

        prompt_library = sorted(prompt_library, key=lambda k: k["name"])
        prompt_library.append(
            {
                "name": "Custom prompt",
                "prompt": [
                    "Prompt: YOUR PROMPT HERE",
                    "",
                    "Text: [body]",
                    "",
                    "Answer:",
                ],
                "authors": "user",
                "paper": "",
                "location_of_input": "replace",
            }
        )

        return prompt_library

    @staticmethod
    def get_available_models(config):
        """
        Get available model providers

        Combine the list defined by the LLMAdapter with known local models.

        :param config:  Configuration reader
        :return dict:  Models and metadata
        """
        # get cached local models
        models = config.get("llm.available_models", {})
        models.update({k: v for k, v in LLMAdapter.get_models(config).items() if k not in ("none", "custom")})

        models = {k: v for k, v in models.items() if "model_card" in v}

        return models

    @staticmethod
    def is_compatible_with(module=None, config=None):
        """
        Determine compatibility

        :param Dataset module:  Module ID to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        :return bool:
        """
        models = PromptCompassRunner.get_available_models(config)
        return (models
                and module.is_top_dataset()
                and module.get_extension() in ("csv", "ndjson"))

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
        """
        Get processor options

        Lots of hacks in here to change fields depending on chosen setting.

        :param parent_dataset:
        :param config:
        :return:
        """
        prompt_library = cls.get_prompt_library(config)
        available_models = cls.get_available_models(config)

        options = {
            "model": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Model to use",
                "tooltip": "Third-party models require an API key to run.",
                "options": {("local/" if v["provider"] == "local" else f"{v['provider']}/") + k: v["name"] for k, v in available_models.items()},
                "default": sorted(list(available_models.keys()), key=lambda k: k.startswith("local"))[-1]
            },
        }

        for model, metadata in available_models.items():
            model_key = metadata["provider"] + "/" + model
            options[f"{model_key}-info"] = {
                "type": UserInput.OPTION_INFO,
                "help": f"Read the [model card]({metadata['model_card']}) for {model}.",
                "requires": f"model=={model_key}"
            }

        options.update({
            "api_key": {
                "type": UserInput.OPTION_TEXT,
                "help": "API key",
                "sensitive": True,
                "cache": True,
                "tooltip": "Create an API key on the LLM provider's website (e.g. https://admin.mistral.ai/organization"
                           "/api-keys). Note that this often involves billing.",
                "requires": "model!^=local"
            },
            "hide_think": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Hide reasoning",
                "default": False,
                "tooltip": "Some models include reasoning in their output, between <think></think> tags. This option "
                           "removes this tag and its contents from the output.",
                "requires": "model^=local/deepseek"
            },
            "temperature": {
                "type": UserInput.OPTION_TEXT,
                "help": "Temperature",
                "tooltip": "Between 0 and 1. Higher temperatures increase variability and may lead to strange results",
                "coerce_type": float,
                "min": 0.0,
                "max": 1.0,
                "default": 0.01
            },
            "task": {
                "type": UserInput.OPTION_CHOICE,
                "options": {},
                "help": "Task",
                "tooltip": "Each task corresponds to a prompt. Some tasks have multiple prompts; the best choice may "
                           "depend on your dataset."
            }
        })

        for i, task in enumerate(prompt_library):
            task_key = f"task-{i+1}"
            options[task_key] = {
                "type": UserInput.OPTION_TEXT_LARGE,
                "requires": f"task=={task_key}",
                "help": "Prompt",
                "tooltip": "[column] will be replaced with the content of that column in the source dataset. For "
                           "example, '[body]' is replaced with the content of the 'body' column.",
                "default": "\n".join(task["prompt"])
            }

            reference = None
            if "paper" in task:
                reference = f"Source: [{task['authors']}]({task['paper']})"
            elif "authors" in task:
                reference = f"Source: {task['authors']}"

            if reference:
                options[task_key + "-ref"] = {
                    "type": UserInput.OPTION_INFO,
                    "help": reference,
                    "requires": f"task=={task_key}",
                }

            label = task["name"] + (f" ({task['authors']})" if task["authors"] else "")
            options["task"]["options"][task_key] = label

        options["limit"] = {
            "type": UserInput.OPTION_TEXT,
            "help": "Only annotate this many items, then stop",
            "tooltip": "You can annotate up to 750 items",
            "default": 50,
            "coerce_type": int,
            "min": 0,
            "max": 750
        }

        if parent_dataset:
            options["limit"]["default"] = int(min(round(parent_dataset.num_rows / 10, 0), 50))

        return options

    def get_processor_pipeline(self):
        """
        This queues the LLM prompter, with some options pre-configured to
        simulate PromptCompass-like functionality.
        """
        prompt_library = self.get_prompt_library(self.config)
        label = ""
        short_name = ""

        try:
            task = prompt_library[int(self.parameters.get("task").split("-")[1]) - 1]
            short_name = task.get("label", task["name"])
            label = short_name.lower().replace(" ", "_")
            model_name = self.parameters['model'].split("/")[1]
            label = f"{label}:{model_name}"
        except (TypeError, IndexError):
            pass

        if short_name:
            self.dataset.update_label(f"PromptCompass ({short_name})")

        chosen_model = "/".join(self.parameters.get("model").split("/")[1:])
        models = self.get_available_models(self.config)
        if chosen_model not in models:
            return self.dataset.finish_with_error(f"Model {self.parameters['model']} is not available, halting processor.")

        model = models[chosen_model]

        pipeline = [
            {
                "type": "llm-prompter",
                "parameters": {
                    "api_or_local": "local" if model["provider"] == "local" else "api",
                    "api_model": chosen_model if model["provider"] != "local" else "",
                    "api_key": self.parameters.get("api_key"),
                    "api_custom_model_provider": "",
                    "local_provider": self.config.get("llm.provider_type"),
                    "local_base_url": self.config.get("llm.server"),
                    "ollama_model": chosen_model if model["provider"] == "local" else "",
                    "prompt": self.parameters[self.parameters["task"]],
                    "structured_output": False,
                    "temperature": self.parameters["temperature"],
                    "truncate_input": 4096,
                    "save_annotations": True,
                    "consent": True,
                    "limit": self.parameters.get("limit"),
                    "annotation_label": label,
                    "hide_think": self.parameters.get("hide_think", False)
                }
            }
        ]

        return pipeline


    @staticmethod
    def validate_query(query, request, config):
        """
        Validate input

        Checks if everything needed is filled in.

        :param query:
        :param request:
        :param config:
        :return:
        """
        if not query["model"].startswith("local") and not query.get("api_key"):
            raise QueryParametersException("You need to enter an API key when using third-party models.")

        if not query[query.get("task")].strip():
            raise QueryParametersException("The prompt cannot be empty.")

        if not query["model"].startswith("local") and not query.get("frontend-confirm"):
            raise QueryNeedsExplicitConfirmationException("Your data will be sent to a third-party service for "
                                                          "processing, which will share your data with them and is "
                                                          "likely to incur costs. Do you want to continue?")

        return query

    @staticmethod
    def map_item(item):
        """
        Map item

        :param item:
        :return:
        """
        return LLMPrompter.map_item(item)