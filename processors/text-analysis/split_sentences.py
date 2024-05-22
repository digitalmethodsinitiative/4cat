"""
Split posts into separate sentences
"""
import csv
from nltk.tokenize import sent_tokenize, word_tokenize

from common.lib.helpers import UserInput
from backend.lib.processor import BasicProcessor

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

	@classmethod
	def get_options(cls, parent_dataset=None, user=None):
		"""
		Get processor options

		:param DataSet parent_dataset:  An object representing the dataset that
		the processor would be run on
		:param User user:  Flask user the options will be displayed for, in
		case they are requested for display in the 4CAT web interface. This can
		be used to show some options only to privileges users.
		"""
		options = {
			"column": {
				"type": UserInput.OPTION_TEXT,
				"help": "Column to split",
				"default": "body",
			},
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

		if parent_dataset and parent_dataset.get_columns():
			columns = parent_dataset.get_columns()
			options["column"]["type"] = UserInput.OPTION_CHOICE
			options["column"]["inline"] = True
			options["column"]["options"] = {v: v for v in columns}

		return options

	@classmethod
	def is_compatible_with(cls, module=None, user=None):
		"""
		Allow CSV and NDJSON datasets
		"""
		return module.get_extension() in ("csv", "ndjson")

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
		column = self.parameters.get("column")

		with self.dataset.get_results_path().open("w", encoding="utf-8") as output:
			writer = csv.DictWriter(output, fieldnames=("post_id", "sentence",))
			writer.writeheader()

			for post in self.source_dataset.iterate_items(self):
				if num_posts % 100 == 0:
					self.dataset.update_status("Processing post %i" % num_posts)

				num_posts += 1
				
				if not post[column]:
					continue
					
				sentences = sent_tokenize(post.get(column, ""), language=language)

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
