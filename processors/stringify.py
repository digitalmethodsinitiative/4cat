"""
Collapse post bodies into one long string
"""
import re
from csv import DictReader

from backend.abstract.processor import BasicProcessor
from backend.lib.helpers import UserInput

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

class Stringify(BasicProcessor):
	"""
	Merge post body into one long string
	"""
	type = "stringify-posts"  # job type ID
	category = "Text analysis" # category
	title = "Merge post texts"  # title displayed in UI
	description = "Collapses all posts in the results into one plain text string. The result can be used for word clouds, word trees, et cetera."  # description displayed in UI
	extension = "txt"  # extension of result file, used internally and in UI

	options = {
		"strip-urls": {
			"type": UserInput.OPTION_TOGGLE,
			"default": True,
			"help": "Remove URLs"
		}
	}

	input = "csv:body"
	output = "txt"

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a plain text file
		containing all post bodies as one continuous string, sanitized.
		"""

		link_regex = re.compile(r"https?://[^\s]+")
		delete_regex = re.compile(r"[^a-zA-Z)(.,\n -]")

		strip_urls = self.parameters.get("strip-urls", self.options["strip-urls"]["default"])

		posts = 0
		self.dataset.update_status("Processing posts")
		with self.dataset.get_results_path().open("w") as results:
			with open(self.source_file, encoding="utf-8") as source:
				csv = DictReader(source)
				for post in csv:
					posts += 1
					if strip_urls:
						post["body"] = link_regex.sub("", post["body"])
					results.write(re.sub(r"\s+", " ", delete_regex.sub(" ", post["body"])).strip() + " ")


		self.dataset.update_status("Finished")
		self.dataset.finish(posts)