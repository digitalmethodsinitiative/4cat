"""
Split posts into separate sentences
"""
import csv
from nltk.tokenize import sent_tokenize, word_tokenize

from common.lib.helpers import UserInput
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
	description = "Split a body of posts into discrete sentences. Output file has one row per sentence, containing the sentence and post ID."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	options = {
		"language": {
			"type": UserInput.OPTION_CHOICE,
			"default": "english",
			"options": {
				"czech": "Czech",
				"danish": "Danish",
				"dutch": "Dutch",
				"english": "English",
				"estonian": "Estonian",
				"finnish": "Finnish",
				"french": "French",
				"german": "German",
				"greek": "Greek",
				"italian": "Italian",
				"norwegian": "Norwegian",
				"polish": "Polish",
				"portuguese": "Portuguese",
				"russian": "Russian",
				"slovene": "Slovene",
				"spanish": "Spanish",
				"swedish": "Swedish",
				"turkish": "Turkish"
			},
			"help": "Language"
		},
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
		min_length = self.parameters.get("min_length")
		language = self.parameters.get("language")

		with self.dataset.get_results_path().open("w", encoding="utf-8") as output:
			writer = csv.DictWriter(output, fieldnames=("post_id", "sentence",))
			writer.writeheader()

			for post in self.iterate_items(self.source_file):
				if num_posts % 100 == 0:
					self.dataset.update_status("Processing post %i" % num_posts)

				num_posts += 1
				
				if not post["body"]:
					continue
					
				sentences = sent_tokenize(post.get("body", ""), language=language)

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
