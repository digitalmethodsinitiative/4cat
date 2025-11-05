"""
Collapse post bodies into one long string
"""
import re
import string

from backend.lib.processor import BasicProcessor
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
	category = "Conversion" # category
	title = "Merge texts"  # title displayed in UI
	description = "Merges the data from the body column into a single text file. The result can be used for word clouds, word trees, etc."  # description displayed in UI
	extension = "txt"  # extension of result file, used internally and in UI

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

	@staticmethod
	def is_compatible_with(module=None, config=None):
		"""
        Determine compatibility; this processor is only compatible with top datasets in CSV or NDJSON format.

        :param str module:  Module ID to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        :return bool:
        """
		return module.is_top_dataset() and module.get_extension() in ("csv", "ndjson")

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