"""
Get the toxicity score for items via Perspective API.
"""

import json

from googleapiclient.errors import HttpError

from common.lib.helpers import UserInput
from backend.lib.processor import BasicProcessor
from googleapiclient import discovery
from common.lib.item_mapping import MappedItem
from common.config_manager import config


class Perspective(BasicProcessor):
    """
    Score items with toxicity and other scores through Google Jigsaw's Perspective API.
    """

    type = "perspective"  # job type ID
    category = "Machine learning"  # category
    title = "Toxicity scores"  # title displayed in UI
    description = (
        "Use the Perspective API to score text with attributes on toxicity, "
        "including 'toxicity', 'insult', and 'profanity'."
    )  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI

    references = [
        "[Perspective API documentation](https://developers.perspectiveapi.com/s/about-the-api)",
        "[Rieder, Bernhard, and Yarden Skop. 2021. 'The fabrics of machine moderation: Studying the technical, "
        "normative, and organizational structure of Perspective API.' Big Data & Society, 8(2).]"
        "(https://doi.org/10.1177/20539517211046181)",
    ]

    config = {
        "api.google.api_key": {
            "type": UserInput.OPTION_TEXT,
            "default": "",
            "help": "Google API key",
            "tooltip": "Can be created on console.cloud.google.com",
        }
    }

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        options = {
            "attributes": {
                "type": UserInput.OPTION_MULTI,
                "help": "Attributes to score",
                "options": {
                    "TOXICITY": "Toxicity",
                    "SEVERE_TOXICITY": "Severe toxicity",
                    "IDENTITY_ATTACK": "Identity attack",
                    "INSULT": "Insult",
                    "PROFANITY": "Profanity",
                    "THREAT": "Threat",
                },
                "default": ["TOXICITY"],
            },
            "write_annotations": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Add attribute scores as annotations to the parent dataset.",
                "default": True,
            },
        }

        api_key = config.get("api.google.api_key", user=user)
        if not api_key:
            options["api_key"] = {
                "type": UserInput.OPTION_TEXT,
                "default": "",
                "help": "Google API key",
                "tooltip": "Can be created on console.cloud.google.com",
            }

        return options

    def process(self):
        api_key = self.parameters.get("api_key")
        self.dataset.delete_parameter("api_key")  # sensitive, delete after use
        if not api_key:
            api_key = config.get("api.google.api_key", user=self.owner)
        if not api_key:
            self.dataset.finish_with_error("You need to provide a valid API key")
            return

        if not self.parameters.get("attributes"):
            self.dataset.finish_with_error(
                "You need to provide a at least one attribute to score"
            )
            return

        write_annotations = self.parameters.get("api_key", True)

        try:
            client = discovery.build(
                "commentanalyzer",
                "v1alpha1",
                developerKey=api_key,
                discoveryServiceUrl="https://commentanalyzer.googleapis.com/$discovery/rest?version=v1alpha1",
                static_discovery=False,
            )
        except HttpError as e:
            error = json.loads(e.content)["error"]["message"]
            self.dataset.finish_with_error(error)

        results = []
        annotations = []
        api_attributes = {attribute: {} for attribute in self.parameters["attributes"]}

        for item in self.source_dataset.iterate_items(self.source_file):
            if item["body"]:
                analyze_request = {
                    "comment": {"text": item["body"]},
                    "requestedAttributes": api_attributes,
                }

                try:
                    response = client.comments().analyze(body=analyze_request).execute()
                except HttpError as e:
                    self.dataset.update_status(str(e))
                    continue

                response["item_id"] = item["id"]
                response["body"] = item["body"]
                results.append(response)

                if write_annotations:
                    for attribute in self.parameters["attributes"]:
                        annotation = {
                            "label": attribute,
                            "item_id": item["id"],
                            "value": response["attributeScores"][attribute][
                                "summaryScore"
                            ]["value"],
                        }
                        annotations.append(annotation)

        # Write annotations
        if write_annotations:
            self.save_annotations(annotations, overwrite=False)

        # Write to file
        with self.dataset.get_results_path().open(
            "w", encoding="utf-8", newline=""
        ) as outfile:
            for result in results:
                outfile.write(json.dumps(result) + "\n")

        self.dataset.finish(len(results))

    @staticmethod
    def map_item(item):
        attribute_scores = {}
        all_attributes = [
            "TOXICITY",
            "SEVERE_TOXICITY",
            "IDENTITY_ATTACK",
            "INSULT",
            "PROFANITY",
            "THREAT",
        ]
        for att in all_attributes:
            if att in item["attributeScores"]:
                attribute_scores[att] = item["attributeScores"][att]["summaryScore"][
                    "value"
                ]

        return MappedItem(
            {"item_id": item["item_id"], "body": item.get("body"), **attribute_scores}
        )
