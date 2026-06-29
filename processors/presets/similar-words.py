"""
Find similar words
"""
from nltk.stem.snowball import SnowballStemmer

from backend.lib.preset import ProcessorPreset
from common.lib.compatibility import Compatibility

from common.lib.helpers import UserInput


class SimilarWords(ProcessorPreset):
	"""
	Run processor pipeline to find similar words
	"""
	type = "preset-similar-words"  # job type ID
	category = "Combined processors"  # category. 'Combined processors' are always listed first in the UI.
	title = "Find similar words"  # title displayed in UI
	description = ("Create a word2vec model to find words used in a similar context as the queried word(s). Only works "
				   "with large datasets (e.g. 100,000+ items).")
	extension = "csv"

	# Allow on top-level CSV/NDJSON datasets
	compatibility = Compatibility(top_dataset_only=True, extensions={"csv", "ndjson"})

	@classmethod
	def get_options(cls, parent_dataset=None, config=None) -> dict:
		"""
		Get processor options

		:param parent_dataset DataSet:  An object representing the dataset that
			the processor would be or was run on. Can be used, in conjunction with
			config, to show some options only to privileged users.
		:param config ConfigManager|None config:  Configuration reader (context-aware)
		:return dict:   Options for this processor
		"""
		return {
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
					"columns": "body",
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