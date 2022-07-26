"""
Extract neologisms
"""
from backend.abstract.preset import ProcessorPreset

from common.lib.helpers import UserInput


class NeologismExtractor(ProcessorPreset):
	"""
	Run processor pipeline to extract neologisms
	"""
	type = "preset-neologisms"  # job type ID
	category = "Combined processors"  # category. 'Combined processors' are always listed first in the UI.
	title = "Extract neologisms"  # title displayed in UI
	description = "Retrieve uncommon terms by deleting all known words. Assumes English-language data. " \
				  "Uses stopwords-iso as its stopword filter."
	extension = "csv"

	references = ["Van Soest, Jeroen. 2019. 'Language Innovation Tracker: Detecting language innovation in online discussion fora.' (MA thesis), Beuls, K. (Promotor), Van Eecke, P. (Advisor).'"]

	options = {
		"timeframe": {
			"type": UserInput.OPTION_CHOICE,
			"default": "month",
			"options": {"all": "Overall", "year": "Year", "month": "Month", "week": "Week", "day": "Day"},
			"help": "Extract neologisms per"
		}
	}

	def get_processor_pipeline(self):
		"""
		This queues a series of post-processors to extract neologisms from a
		dataset through Van Soest (2019)'s protocol. The resulting top vector
		ranking is used as the result of this processor, once available.
		"""
		timeframe = self.parameters.get("timeframe")

		pipeline = [
			# first, tokenise the posts, excluding all common words
			{
				"type": "tokenise-posts",
				"parameters": {
					"stem": False,
					"strip_symbols": True,
					"lemmatise": False,
					"timeframe": timeframe,
					"filter": ["wordlist-googlebooks-english", "stopwords-iso-all"]
				}
			},
			# then, create vectors for those tokens
			{
				"type": "vectorise-tokens",
				"parameters": {}
			},
			# finally, the top vectors constitute the result of this preset
			{
				"type": "vector-ranker",
				"parameters": {
					"amount": True,
					"top": 15,
				}
			}
		]

		return pipeline