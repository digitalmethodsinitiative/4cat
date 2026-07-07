"""
Find similar words
"""
from nltk.stem.snowball import SnowballStemmer

from backend.lib.preset import ProcessorPreset
from backend.lib.processor import ProcessorDescription
from common.lib.compatibility import Compatibility
from common.lib.outputs import Delegated

from common.lib.helpers import UserInput


class SimilarWords(ProcessorPreset):
	"""
	Run processor pipeline to find similar words
	"""
	type = "preset-similar-words"  # job type ID
	description = ProcessorDescription(
		title="Find similar words",
		category="Combined processors",
		tags=["similarity", "extract"],
		description="Train a word2vec model on the dataset to find words used in a context similar to the words you enter.",
		warnings=[
			"This only produces useful results on large datasets, roughly 100,000 items or more.",
		],
		icon="comments",
	)
	extension = "csv"
	# a preset; its output is its last step's
	output = Delegated()

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