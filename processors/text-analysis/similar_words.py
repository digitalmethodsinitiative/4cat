"""
Find similar words based on word2vec modeling
"""
import shutil

from gensim.models import KeyedVectors

from common.lib.helpers import UserInput, convert_to_int
from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen", "Stijn Peeters"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


class SimilarWord2VecWords(BasicProcessor):
	"""
	Find similar words based on word2vec modeling
	"""
	type = "similar-word2vec"  # job type ID
	category = "Text analysis"  # category
	title = "Similar words"  # title displayed in UI
	description = "Uses a Word2Vec model to find words used in a similar context"  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	options = {
		"words": {
			"type": UserInput.OPTION_TEXT,
			"help": "Words",
			"tooltip": "Separate with commas."
		},
		"num-words": {
			"type": UserInput.OPTION_TEXT,
			"help": "Amount of similar words",
			"min": 1,
			"default": 10,
			"max": 50
		},
		"threshold": {
			"type": UserInput.OPTION_TEXT,
			"help": "Similarity threshold",
			"tooltip": "Decimal value between 0 and 1; only words with a higher similarity score than this will be included",
			"default": "0.25"
		},
		"crawl_depth": {
			"type": UserInput.OPTION_CHOICE,
			"default": 1,
			"options": {"1": 1, "2": 2, "3": 3},
			"help": "The crawl depth. 1 only gets the neighbours of the input word(s), 2 also their neighbours, etc."
		}
	}

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor on word embedding models

		:param module: Dataset or processor to determine compatibility with
		"""
		return module.type == "generate-embeddings"

	def process(self):
		"""
		This takes previously generated Word2Vec models and uses them to find
		similar words based on a list of words
		"""
		self.dataset.update_status("Processing sentences")

		depth = max(1, min(3, convert_to_int(self.parameters.get("crawl_depth"))))
		input_words = self.parameters.get("words", "")
		if not input_words or not input_words.split(","):
			self.dataset.update_status("No input words provided, cannot look for similar words.", is_final=True)
			self.dataset.finish(0)
			return

		input_words = input_words.split(",")

		num_words = convert_to_int(self.parameters.get("num-words", 10))
		try:
			threshold = float(self.parameters.get("threshold", 0.25))
		except ValueError:
			threshold = float(self.get_options()["threshold"]["default"])

		threshold = max(-1.0, min(1.0, threshold))

		# go through all models and calculate similarity for all given input words
		result = []
		staging_area = self.unpack_archive_contents(self.source_file)
		for model_file in staging_area.glob("*.model"):
				interval = model_file.stem

				# for each separate model, calculate top similar words for each
				# input word, giving us at most
				#   [max amount] * [number of input] * [number of intervals]
				# items
				self.dataset.update_status("Running model %s..." % model_file.name)
				model = KeyedVectors.load(str(model_file))
				word_queue = set()
				checked_words = set()
				level = 1

				words = input_words.copy()
				while words:
					if self.interrupted:
						shutil.rmtree(staging_area)
						raise ProcessorInterruptedException("Interrupted while extracting similar words")

					word = words.pop()
					checked_words.add(word)

					try:
						similar_words = model.most_similar(positive=[word], topn=num_words)
					except KeyError:
						continue

					for similar_word in similar_words:
						if similar_word[1] < threshold:
							continue

						result.append({
							"date": interval,
							"input": word,
							"item": similar_word[0],
							"value": similar_word[1],
							"input_occurences": model.vocab[word].count,
							"item_occurences": model.vocab[similar_word[0]].count,
							"depth": level
						})

						# queue word for the next iteration if there is one and
						# it hasn't been seen yet
						if level < depth and similar_word[0] not in checked_words:
							word_queue.add(similar_word[0])

					# if all words have been checked, but we still have an
					# iteration to go, load the queued words into the list
					if not words and word_queue and level < depth:
						level += 1
						words = word_queue.copy()
						word_queue = set()

		shutil.rmtree(staging_area)

		if not result:
			self.dataset.update_status("None of the words were found in the word embedding model.", is_final=True)
			self.dataset.finish(0)
		else:
			self.write_csv_items_and_finish(result)