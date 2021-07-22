"""
Collapse post bodies into one long string
"""
import re

from backend.abstract.processor import BasicProcessor
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
	title = "Merge post texts"  # title displayed in UI
	description = "Collapses all posts in the results into one plain text string. The result can be used for word clouds, word trees, et cetera."  # description displayed in UI
	extension = "txt"  # extension of result file, used internally and in UI

	options = {
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
		strip_numbers = self.parameters.get("strip-numbers")
		to_lowercase = self.parameters.get("to-lowercase")

		link_regex = re.compile(r"https?://[^\s]+")\

		if strip_numbers:
			delete_regex = re.compile(r"[^a-zA-Z)(.,\n -]")
		else:
			delete_regex = re.compile(r"[^a-zA-Z0-9)(.,\n -]")

		posts = 0
		self.dataset.update_status("Processing posts")
		with self.dataset.get_results_path().open("w") as results:
			for post in self.iterate_items(self.source_file):
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