"""
Prompt OpenAI GPT LLMs.
"""

import json
import re
import openai

from common.lib.helpers import UserInput
from backend.lib.processor import BasicProcessor
from common.config_manager import config

class OpenAI(BasicProcessor):
	"""
	Prompt OpenAI's GPT models
	"""
	type = "openai-llms"  # job type ID
	category = "Machine learning"  # category
	title = "OpenAI prompting"  # title displayed in UI
	description = ("Use OpenAI's LLM models (e.g. GPT-4) to generate text based on the parent dataset. This is a generic "
				   "processor that can be used for a variety of tasks, like classification or entity extraction.") # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI. In this case it's variable!

	references = [
		"[OpenAPI documentation](https://platform.openai.com/docs/concepts)",
		"[Karjus, Andres. 2023. 'Machine-assisted mixed methods: augmenting humanities and social sciences "
		"with artificial intelligence.' arXiv preprint arXiv:2309.14379.]"
		"(https://arxiv.org/abs/2309.14379)",
		"[Törnberg, Petter. 2023. 'How to Use LLMs for Text Analysis.' arXiv:2307.13106.](https://arxiv.org/pdf/2307.13106)"]

	config = {
		"api.openai.api_key": {
			"type": UserInput.OPTION_TEXT,
			"default": "",
			"help": "OpenAI API key",
			"tooltip": "Can be created on platform.openapi.com"
		}
	}

	@classmethod
	def get_options(cls, parent_dataset=None, user=None):
		options = {
			"per_item": {
				"type": UserInput.OPTION_INFO,
				"help": "Prompts are ran per row. Use [brackets] with a column name to "
						"indicate what input value you want to use. For instance: 'Determine the language of the "
						"following text: [body]').",
			},
			"ethics_warning1": {
				"type": UserInput.OPTION_INFO,
				"help": "Before running a prompt on a large dataset, first create a sample to "
						"test the prompt on a handful of rows. You can sample your dataset with the filter processors"
						" on this page."
			},
			"model": {
				"type": UserInput.OPTION_CHOICE,
				"help": "Model",
				"options": {
					"gpt-4o-mini": "GPT-4o mini",
					"gpt-4o": "GPT-4o",
					"gpt-4-turbo": "GPT-4 turbo",
					"o1-mini": "o1-mini",
					"custom": "Custom (fine-tuned) model"
				},
				"default": "gpt-4o-mini"
			},
			"custom_model_info": {
				"type": UserInput.OPTION_INFO,
				"requires": "model==custom",
				"help": "[You can fine-tune a model on the OpenAI portal to improve your prompt results]("
						"https://platform.openai.com/docs/guides/fine-tuning). With fine-tuned models, examples in the "
						"prompt ('few-shot learning') may not be necessary anymore."
			},
			"custom_model": {
				"type": UserInput.OPTION_TEXT,
				"help": "Model ID",
				"requires": "model==custom",
				"tooltip": "In the format ft:[modelname]:[org_id]:[custom_suffix]:[id]. See link above"
			},
			"prompt": {
				"type": UserInput.OPTION_TEXT_LARGE,
				"help": "Prompt",
				"tooltip": "See the academic references for this processor on best practices for LLM prompts"
			},
			"temperature": {
				"type": UserInput.OPTION_TEXT,
				"help": "Temperature",
				"default": 0.5,
				"tooltip": "The temperature hyperparameter indicates how strict the model will gravitate towards the next "
						   "predicted word with the highest probability. A score close to 0 returns more predictable "
						   "outputs while a score close to 1 leads to more creative outputs."
			},
			"max_tokens": {
				"type": UserInput.OPTION_TEXT,
				"help": "Max output tokens",
				"default": 50,
				"tooltip": "As a rule of thumb, one token generally corresponds to ~4 characters of "
						   "text for common English text."
			},
			"ethics_warning2": {
				"type": UserInput.OPTION_INFO,
				"help": "<strong>Be very sensitive with running this processor on your datasets, as data will be "
						"sent to OpenAI.</strong>"
			},
			"ethics_warning3": {
				"type": UserInput.OPTION_INFO,
				"help": "<strong>Always consider anonymising your data and using local, open-source LLMs.</strong>"
			},
			"consent": {
				"type": UserInput.OPTION_TOGGLE,
				"help": "I understand that my data is sent to OpenAI and that OpenAI may incur costs.",
				"default": False,
			}
		}

		# Allow adding prompt answers as annotations to the top-level dataset
		# if this is a direct child
		# if parent_dataset and parent_dataset.is_top_dataset():
		# todo: update when explorer is integrated
		# 	options["write_annotations"] = {
		# 			"type": UserInput.OPTION_TOGGLE,
		# 			"help": "Add output as annotations to the parent dataset.",
		# 			"default": True
		# 	}
		# 	options["annotation_label"] = {
		# 			"type": UserInput.OPTION_TEXT,
		# 			"help": "Annotation label",
		# 			"default": "",
		# 			"requires": "write_annotations==true"
		# 	}

		api_key = config.get("api.openai.api_key", user=user)
		if not api_key:
			options["api_key"] = {
				"type": UserInput.OPTION_TEXT,
				"default": "",
				"help": "OpenAI API key",
				"tooltip": "Can be created on platform.openapi.com"
			}

		return options

	@classmethod
	def is_compatible_with(cls, module=None, user=None):
		"""
		Determine if processor is compatible with a dataset or processor

		:param module: Module to determine compatibility with
		"""

		return module.get_extension() in ["csv", "ndjson"]

	def process(self):

		consent = self.parameters.get("consent", False)
		if not consent:
			self.dataset.finish_with_error("You must consent to your data being sent to OpenAI first")
			return

		self.dataset.delete_parameter("consent")

		model = self.parameters.get("model")
		if model == "custom":
			if not self.parameters.get("custom_model", ""):
				self.dataset.finish_with_error("You must provide a valid ID for your custom model")
				return
			else:
				custom_model_id = self.parameters.get("custom_model", "")
				self.parameters["model"] = custom_model_id
				model = custom_model_id

		api_key = self.parameters.get("api_key")
		if not api_key:
			api_key = config.get("api.openai.api_key", user=self.owner)
		if not api_key:
			self.dataset.finish_with_error("You need to provide a valid API key")
			return

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

		self.dataset.delete_parameter("api_key")  # sensitive, delete after use

		base_prompt = self.parameters.get("prompt", "")
		self.dataset.update_status("Prompt: %s" % base_prompt)

		if not base_prompt:
			self.dataset.finish_with_error("You need to insert a valid prompt")
			return

		replacements = re.findall(r"\[.*?\]", base_prompt)
		if not replacements:
			self.dataset.finish_with_error("You need to provide the prompt with input values using [brackets] of "
										   "column names")
			return

		write_annotations = False
		# todo: update when explorer is integrated
		#write_annotations = self.parameters.get("write_annotations", False)

		if write_annotations:
			label = self.parameters.get("annotation_label", "")
			if not label:
				label = model + " output"

		annotations = []

		results = []

		# initiate
		client = openai.OpenAI(api_key=api_key)
		i = 1

		for item in self.source_dataset.iterate_items():

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
				response = self.prompt_gpt(prompt, client, model=model, temperature=temperature, max_tokens=max_tokens)
			except openai.NotFoundError as e:
				self.dataset.finish_with_error(e.message)
				return
			except openai.BadRequestError as e:
				self.dataset.finish_with_error(e.message)
				return
			except openai.AuthenticationError as e:
				self.dataset.finish_with_error(e.message)
				return

			if "id" in item:
				item_id = item["id"]
			elif "item_id" in item:
				item_id = item["item_id"]
			else:
				item_id = str(i)

			response = response.choices[0].message.content
			results.append({
				"id": item_id,
				"prompt": prompt,
				model + " output": response
			})

			if write_annotations:
				annotation = {
					"label": label,
					"item_id": item_id,
					"value": response,
					"type": "textarea"
				}
				annotations.append(annotation)

			self.dataset.update_status("Generated output for item %s/%s" % (i, self.source_dataset.num_rows))
			i += 1

		# Write annotations
		# todo: update when explorer is integrated
		# if write_annotations:
		#	self.write_annotations(annotations, overwrite=True)

		# Write to csv file
		self.write_csv_items_and_finish(results)

	@staticmethod
	def prompt_gpt(prompt, client, model="gpt-4-turbo", temperature=0.2, max_tokens=50):

		# Get response
		response = client.chat.completions.create(
			model=model,
			temperature=temperature,
			max_tokens=max_tokens,
			messages=[{
				"role": "user",
				"content": prompt
			}]
		)

		return response
