"""
Prompt OpenAI GPT LLMs.
"""

import json
import re
import openai

from common.lib.helpers import UserInput
from backend.lib.processor import BasicProcessor
from common.config_manager import config

class GPT(BasicProcessor):
	"""
	Prompt OpenAI's GPT models
	"""
	type = "gpt"  # job type ID
	category = "Machine learning"  # category
	title = "GPT prompting"  # title displayed in UI
	description = ("Use OpenAI's GPT LLMs to generate outputs based on the parent dataset. "
				   "Note: Be very sensitive with running this processor on your datasets, "
				   "as data will be given to OpenAI.") # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI. In this case it's variable!

	references = [
		"[OpenAPI documentation](https://platform.openai.com/docs/concepts)",
		"[Karjus, Andres. 2023. 'Machine-assisted mixed methods: augmenting humanities and social sciences "
		"with artificial intelligence.' arXiv preprint arXiv:2309.14379.]"
		"(https://arxiv.org/abs/2309.14379)",
		"[Törnberg, Petter. 2023. 'How to Use LLMs for Text Analysis.' arXiv:2307.13106.]"
		"(https://arxiv.org/abs/2307.13106)"
	]

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
			"model": {
				"type": UserInput.OPTION_CHOICE,
				"help": "Model",
				"options": {
					"gpt-4o-mini": "GPT-4o mini",
					"gpt-4o": "GPT-4o",
					"gpt-4-turbo": "GPT-4 turbo",
				},
				"default": "gpt-4o-mini"
			},
			"per_item": {
				"type": UserInput.OPTION_INFO,
				"help": "Outputs are generated per row in the parent dataset. Use [brackets] with a column name to indicate where and what dataset value you want to use, e.g.: 'Determine the language of the following text: [body]')",
			},
			"prompt": {
				"type": UserInput.OPTION_TEXT_LARGE,
				"help": "Prompt"
			},
			"temperature": {
				"type": UserInput.OPTION_TEXT,
				"help": "Temperature",
				"default": 0.5
			},
			"max_tokens": {
				"type": UserInput.OPTION_TEXT,
				"help": "Max tokens",
				"default": 50
			},
			"write_annotations": {
				"type": UserInput.OPTION_TOGGLE,
				"help": "Add output as annotations to the parent dataset.",
				"default": True
			}
		}

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

		model = self.parameters.get("model")

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

		try:
			max_tokens = int(self.parameters.get("max_tokens"))
		except ValueError:
			self.dataset.finish_with_error("Max tokens must be a number")

		self.dataset.delete_parameter("api_key")  # sensitive, delete after use

		base_prompt = self.parameters.get("prompt", "")

		if not base_prompt:
			self.dataset.finish_with_error("You need to insert a valid prompt")
			return

		replacements = re.findall(r"\[(.*?)\]", base_prompt)
		if not replacements:
			self.dataset.finish_with_error("You need to provide the prompt with input values using [brackets] of "
										   "column names.")

		write_annotations = self.parameters.get("write_annotations", False)
		annotations = []

		results = []

		# initiate
		client = openai.OpenAI(api_key=api_key)
		i = 1

		for item in self.source_dataset.iterate_items():

			# Replace with dataset values
			prompt = base_prompt
			for replacement in replacements:
				prompt = prompt.replace(replacement, str(item[replacement]))

			response = self.prompt_gpt(prompt, client, model=model, temperature=temperature, max_tokens=max_tokens)

			item_id = item["id"] if "id" in item else item.get("item_id", "")

			response = response.choices[0].message.content
			results.append({
				"id": item_id,
				"prompt": prompt,
				model + " output": response
			})

			# todo: make this available for all datasets
			if self.source_dataset.is_top_dataset() and write_annotations:
				annotation = {
					"label": model + " output",
					"item_id": item_id,
					"value": response,
					"type": "textarea"
				}
				annotations.append(annotation)

			self.dataset.update_status("Generated output for item %s/%s" % (i, self.source_dataset.num_rows))
			i += 1

		# Write annotations
		if self.source_dataset.is_top_dataset() and write_annotations:
			self.write_annotations(annotations, overwrite=True)

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
