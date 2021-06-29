"""
Find similar words
"""
from nltk.stem.snowball import SnowballStemmer

from backend.abstract.preset import ProcessorPreset

from common.lib.helpers import UserInput


class SimilarWords(ProcessorPreset):
	"""
	Run processor pipeline to find similar words
	"""
	type = "preset-similar-words"  # job type ID
	category = "Presets"  # category. 'Presets' are always listed first in the UI.
	title = "Find similar words"  # title displayed in UI
	description = "Uses Word2Vec models (Mikolov et al.) to find words used in a similar context as the queried word(s). Note that this will usually not give useful results for small (<100.000 items) datasets."
	extension = "csv"

	options = {
		"words": {
			"type": UserInput.OPTION_TEXT,
			"help": "Words",
			"tooltip": "Separate with commas."
		},
		"timeframe": {
			"type": UserInput.OPTION_CHOICE,
			"default": "all",
			"options": {"all": "Overall", "year": "Year", "month": "Month", "week": "Week", "day": "Day"},
			"help": "Calculate similarities per"
		},
		"language": {
			"type": UserInput.OPTION_CHOICE,
			"options": {language: language[0].upper() + language[1:] for language in SnowballStemmer.languages},
			"default": "english",
			"help": "Language"
		}
	}

	def get_processor_pipeline(self):
		"""
		This queues a series of post-processors to calculate word similarities
		with the Word2Vec (Mikolov et al.) algorithm.
		"""
		timeframe = self.parameters.get("timeframe")
		language = self.parameters.get("language")
		words = self.parameters.get("words", "")

		pipeline = [
			# first, tokenise the posts, excluding all common words
			{
				"type": "tokenise-posts",
				"parameters": {
					"stem": False,
					"lemmatise": False,
					"timeframe": timeframe,
					"grouping-per": "sentence",
					"language": language
				}
			},
			# then, generate word2vec models
			{
				"type": "generate-embeddings",
				"parameters": {
					"model-type": "Word2Vec"
				}
			},
			# finally, run the similar words analysis
			{
				"type": "similar-word2vec",
				"parameters": {
					"words": words
				}
			}
		]

		return pipeline