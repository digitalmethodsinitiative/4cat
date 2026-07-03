"""
Collapse post bodies into one long string
"""
import re
import string

from backend.lib.processor import BasicProcessor, ProcessorDescription
from common.lib.compatibility import Compatibility
from common.lib.outputs import File
from common.lib.helpers import UserInput

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

class Stringify(BasicProcessor):
	"""
	Merge post body into one long string
	"""
	type = "stringify-posts"  # job type ID
	description = ProcessorDescription(
		title="Merge texts",
		category="Conversion",
		tags=["clean text"],
		description="Merge the text from the body column of every item into a single continuous text file. Optionally strip URLs, numbers, or punctuation, and convert the text to lowercase.",
		info=[
			"The output works well as input for word clouds, word trees, and similar text visualisations.",
		],
		icon="file-lines",
	)
	extension = "txt"  # extension of result file, used internally and in UI
	# a single txt file
	output = File("txt")

	# Allow on top-level CSV/NDJSON datasets
	compatibility = Compatibility(top_dataset_only=True, extensions={"csv", "ndjson"})

	@classmethod
	def get_options(cls, parent_dataset=None, config=None) -> dict:
		"""
		Get processor options

		:param parent_dataset DataSet:  An object representing the dataset that
			the processor would be or was run on. Can be used, in conjunction with
			config, to show some options only to privileged users.
			config, to show some options only to privileged users.
		:param config ConfigManager|None config:  Configuration reader (context-aware)
		:return dict:   Options for this processor
		""" 
		return {
			"strip-urls": {
				"type": UserInput.OPTION_TOGGLE,
				"default": True,
				"help": "Remove URLs"
			},
			"strip-numbers": {
				"type": UserInput.OPTION_TOGGLE,
				"default": False,
				"help": "Remove numbers"
			},
			"strip-punctuation": {
				"type": UserInput.OPTION_TOGGLE,
				"default": False,
				"help": "Remove punctuation"
			},
			"to-lowercase": {
				"type": UserInput.OPTION_TOGGLE,
				"default": True,
				"help": "Convert text to lowercase"
			}
		}

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a plain text file
		containing all post bodies as one continuous string, sanitized.
		"""

		strip_urls = self.parameters.get("strip-urls")
		strip_punctuation = self.parameters.get("strip-punctuation")
		strip_numbers = self.parameters.get("strip-numbers")
		to_lowercase = self.parameters.get("to-lowercase")

		link_regex = re.compile(r"https?://[^\s]+")\

		regex = ""
		if strip_numbers:
			regex += "0-9"
		if strip_punctuation:
			regex += string.punctuation

		delete_regex = re.compile("[\n\t" + regex + "]")

		posts = 0
		self.dataset.update_status("Processing posts")
		with self.dataset.get_results_path().open("w", encoding="utf-8") as results:
			for post in self.source_dataset.iterate_items(self):
				posts += 1
				if not post["body"]:
					continue

				if strip_urls:
					post["body"] = link_regex.sub("", post["body"])

				if to_lowercase:
					post["body"] = post["body"].lower()

				# Keeps words like "isn't" intact
				post["body"] = post["body"].replace("'", "")

				results.write(re.sub(r"\s+", " ", delete_regex.sub(" ", post["body"])).strip() + " ")

		self.dataset.update_status("Finished")
		self.dataset.finish(posts)