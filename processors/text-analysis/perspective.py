"""
Get the toxicity score for items via Perspective API.
"""
import json

from googleapiclient.errors import HttpError

from common.lib.helpers import UserInput
from backend.lib.processor import BasicProcessor
from googleapiclient import discovery
from google.auth.exceptions import DefaultCredentialsError

from common.lib.exceptions import AnnotationException

class Perspective(BasicProcessor):
	"""
	---
	"""
	type = "perspective"  # job type ID
	category = "Text analysis"  # category
	title = "Toxicity scores"  # title displayed in UI
	description = ("Use the Perspective API to score text with attributes on toxicity, "
					"including 'toxicity', 'insult', and 'profanity'.")		# description displayed in UI
	extension = "ndjson"  # extension of result file, used internally and in UI

	references = [
		"[Perspective API documentation](https://developers.perspectiveapi.com/s/about-the-api)",
		"[Rieder, Bernhard, and Yarden Skop. 2021. 'The fabrics of machine moderation: Studying the technical, "
		"normative, and organizational structure of Perspective API.' Big Data & Society, 8(2).]"
		"(https://doi.org/10.1177/20539517211046181)"
	]

	options = {
		"api_key": {
            "type": UserInput.OPTION_TEXT,
            "help": "API Key",
            "tooltip": "The API Key for the Google API account you want to query with. You can generate and find this "
                       "key on the API dashboard.",
			"sensitive": True
        },
        "attributes": {
            "type": UserInput.OPTION_MULTI,
            "help": "Attributes to score",
            "options": {
                "TOXICITY": "Toxicity",
                "SEVERE_TOXICITY": "Severe toxicity",
                "IDENTITY_ATTACK": "Identity attack",
                "INSULT": "Insult",
                "PROFANITY": "Profanity",
                "THREAT": "Threat"
            },
            "default": ["TOXICITY"]
        },
		"write_annotations": {
			"type": UserInput.OPTION_TOGGLE,
			"help": "Add attribute scores as annotations to the parent dataset.",
			"default": True
		}
	}

	def process(self):

		api_key = self.parameters.get("api_key")
		self.dataset.delete_parameter("api_key")  # sensitive, delete after use

		if not api_key:
			self.dataset.finish_with_error("You need to provide a valid API key")
			return

		if not self.parameters.get("attributes"):
			self.dataset.finish_with_error("You need to provide a at least one attribute to score")
			return

		write_annotations = self.parameters.get("api_key", True)

		client = discovery.build(
			"commentanalyzer",
			"v1alpha1",
			developerKey=api_key,
			discoveryServiceUrl="https://commentanalyzer.googleapis.com/$discovery/rest?version=v1alpha1",
			static_discovery=False,
		)

		results = []
		annotations = []
		api_attributes = {attribute: {} for attribute in self.parameters["attributes"]}

		for item in self.source_dataset.iterate_items(self.source_file):

			if item["body"]:

				analyze_request = {
					"comment": {"text": item["body"]},
					"requestedAttributes": api_attributes
				}

				try:
					response = client.comments().analyze(body=analyze_request).execute()
				except HttpError as e:
					self.dataset.update_status(str(e))
					continue

				results.append({item["id"]: response})

				if write_annotations:
					for attribute in self.parameters["attributes"]:
						annotation = {
							"label": attribute,
							"item_id": item["id"],
							"value": response["attributeScores"][attribute]["summaryScore"]["value"],
						}
						annotations.append(annotation)

		if write_annotations:
			self.write_annotations(annotations, overwrite=True)

		with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile:
			for result in results:
				outfile.write(json.dumps(result) + "\n")

		self.dataset.finish(len(results))