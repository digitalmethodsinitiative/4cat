"""
Generate co-link network of URLs in posts
"""
from backend.abstract.processor import BasicProcessor

from backend.lib.dataset import DataSet
from backend.lib.helpers import UserInput

class URLCoLinker(BasicProcessor):
	"""
	Generate URL co-link network
	"""
	type = "preset-neologisms"  # job type ID
	category = "Presets"  # category
	title = "Extract neologisms"  # title displayed in UI
	description = "Follows Van Soest (2019)'s protocol to extract neologisms - hitherto unused words - from the dataset. Assumes English-language data. Uses stopwords-iso as its stopword filter."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

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
		This takes a 4CAT results file as input, and outputs a new CSV file
		with all posts containing the original query exactly, ignoring any
		* or " in the query
		"""
		timeframe = self.parameters.get("timeframe", self.options["timeframe"]["default"])

		analysis = DataSet(parameters={
			"next": [{
				"type": "vectorise-tokens",
				"parameters": {
					"next": [{
						"type": "vector-ranker",
						"parameters": {
							"amount": True,
							"top": 15,
							"copy_to": self.dataset.key
						}
					}]
				}
			}],
			"echobrackets": False,
			"stem": False,
			"strip_symbols": True,
			"lemmatise": False,
			"timeframe": timeframe,
			"filter": ["wordlist-googlebooks-min40", "stopwords-iso-all"]
		}, type="tokenise-posts", db=self.db, parent=self.dataset.key_parent)
		self.queue.add_job("tokenise-posts", remote_id=analysis.key)

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