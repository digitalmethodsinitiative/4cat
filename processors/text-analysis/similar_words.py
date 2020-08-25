"""
Find similar words based on word2vec modeling
"""
import zipfile
import shutil

from gensim.models import Word2Vec

from backend.lib.helpers import UserInput, convert_to_int
from backend.abstract.processor import BasicProcessor
from backend.lib.exceptions import ProcessorInterruptedException

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters", "Tom Willaert"]
__maintainer__ = "Stijn Peeters"
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

	accepts = ["generate-word2vec"]

	input = "zip"
	output = "csv:time,input,item,value"

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
			"tooltip": "Number between 0 and 1; only words with a higher similarity score than this will be included",
			"min": 0,
			"max": 1,
			"default": "0.25"
		}
	}

	def process(self):
		"""
		This takes previously generated Word2Vec models and uses them to find
		similar words based on a list of words
		"""
		self.dataset.update_status("Processing sentences")

		words = self.parameters.get("words", "").split(",")
		if not words:
			self.dataset.update_status("No input words provided, cannot look for similar words.", is_final=True)
			self.dataset.finish(-1)
			return

		num_words = convert_to_int(self.parameters.get("num-words"), self.options["num-words"]["default"])
		try:
			threshold = float(self.parameters.get("threshold", self.options["threshold"]["default"]))
		except ValueError:
			threshold = float(self.options["threshold"]["default"])

		# prepare staging area
		temp_path = self.dataset.get_temporary_path()
		temp_path.mkdir()

		# go through all models and calculate similarity for all given input words
		result = []
		with zipfile.ZipFile(self.source_file, "r") as model_archive:
			model_files = model_archive.namelist()

			for model_file in model_files:
				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while processing token sets")

				# the model is stored as [interval].model
				model_name = model_file.split("/")[-1]
				interval = model_name.split(".")[0]

				# temporarily extract file (we cannot use ZipFile.open() as it doesn't support binary modes)
				temp_file = temp_path.joinpath(model_name)
				model_archive.extract(model_name, temp_path)

				# for each separate model, calculate top similar words for each
				# input word, giving us at most
				#   [max amount] * [number of input] * [number of intervals]
				# items
				self.dataset.update_status("Running model %s..." % model_name)
				model = Word2Vec.load(str(temp_file))
				for word in words:
					similar_words = model.most_similar(positive=[word], topn=num_words)
					for similar_word in similar_words:
						if similar_word[1] < threshold:
							continue

						result.append({
							"date": interval,
							"input": word,
							"item": similar_word[0],
							"value": similar_word[1]
						})

				temp_file.unlink()

		# delete temporary folder
		shutil.rmtree(temp_path)

		self.write_csv_items_and_finish(result)