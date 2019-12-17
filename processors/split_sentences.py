"""
Split posts into separate sentences
"""
import csv
from nltk.tokenize import sent_tokenize, word_tokenize

from backend.lib.helpers import UserInput
from backend.abstract.processor import BasicProcessor

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

class SplitSentences(BasicProcessor):
	"""
	Split sentences
	"""
	type = "sentence-split"  # job type ID
	category = "Text analysis"  # category
	title = "Sentence split"  # title displayed in UI
	description = "Split a body of posts into discrete sentences. Assumes the posts are written in English; success for other languages, particularly those using other punctuation systems, may vary."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	input = "csv:id,body"
	output = "csv:post_id,sentence"

	options = {
		"min_length": {
			"type": UserInput.OPTION_TEXT,
			"min": 0,
			"max": 100,
			"default": 3,
			"help": "Minimal amount of tokens (words) per sentence"
		}
	}

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a number of files containing
		tokenised posts, grouped per time unit as specified in the parameters.
		"""
		self.dataset.update_status("Processing posts")

		num_sentences = 0
		num_posts = 1
		min_length = self.parameters.get("min_length", self.options["min_length"]["default"])

		with self.dataset.get_results_path().open("w") as output:
			writer = csv.DictWriter(output, fieldnames=("post_id", "sentence",))
			writer.writeheader()

			with self.source_file.open("r") as input:
				reader = csv.DictReader(input)

				for post in reader:
					self.dataset.update_status("Processing post %i" % num_posts)
					num_posts += 1
					sentences = sent_tokenize(post.get("body", ""))

					for sentence in sentences:
						if min_length == 0:
							num_sentences += 1
							writer.writerow({"sentence": sentence})
						else:
							# use NLTK's tokeniser to determine word count
							words = word_tokenize(sentence)
							if len(words) >= min_length:
								num_sentences += 1
								writer.writerow({"post_id": post.get("id", ""), "sentence": sentence})

		# done!
		self.dataset.update_status("Finished")
		self.dataset.finish(num_sentences)
