"""
Extract neologisms
"""
from backend.abstract.processor import BasicProcessor

from backend.lib.dataset import DataSet
from backend.lib.helpers import UserInput


class NeologismExtractor(BasicProcessor):
	"""
	Run post-processor chain to extract neologisms
	"""
	type = "preset-neologisms"  # job type ID
	category = "Presets"  # category. 'Presets' are always listed first in the UI.
	title = "Extract neologisms"  # title displayed in UI
	description = "Follows Van Soest (2019)'s protocol to extract neologisms - hitherto unused words - " \
				  "from the dataset. Assumes English-language data. Uses stopwords-iso as its stopword " \
				  "filter."
	extension = "csv"

	options = {
		"timeframe": {
			"type": UserInput.OPTION_CHOICE,
			"default": "month",
			"options": {"all": "Overall", "year": "Year", "month": "Month", "day": "Day"},
			"help": "Extract neologisms per"
		}
	}

	def process(self):
		"""
		This queues a series of post-processors to extract neologisms from a
		dataset through Van Soest (2019)'s protocol. The resulting top vector
		ranking is used as the result of this processor, once available.
		"""
		timeframe = self.parameters.get("timeframe", self.options["timeframe"]["default"])

		# processors are chained through the "next" parameter, which takes a
		# list of dataset parameters (i.e. the parameters= argument for
		# DataSet()). These may be nested at will
		analysis_chain = DataSet(parameters={
			"next": [{
				"type": "vectorise-tokens",
				"parameters": {
					"next": [{
						"type": "vector-ranker",
						"parameters": {
							"amount": True,
							"top": 15,
							"attach_to": self.dataset.key  # copy to the dataset with this key
						}
					}]
				}
			}],
			"stem": False,
			"strip_symbols": True,
			"lemmatise": False,
			"timeframe": timeframe,
			"filter": ["wordlist-googlebooks-english", "stopwords-iso-all"]
		}, type="tokenise-posts", db=self.db, parent=self.dataset.key_parent)

		# this starts the chain
		self.queue.add_job("tokenise-posts", remote_id=analysis_chain.key)

	def after_process(self):
		"""
		Run after processing

		In this case, this is run immediately after the underlying analyses
		have been queued. This overrides the default behaviour which finishes
		the DataSet after processing; in this case, it is left 'open' until it
		is finished by the last underlying analysis, in this case the vector
		ranker.
		"""
		self.dataset.update_status("Awaiting completion of underlying analyses...")
		self.job.finish()
