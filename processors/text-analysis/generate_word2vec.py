"""
Generate interval-based Word2Vec models for sentences
"""
import datetime
import zipfile
import shutil
import json

from gensim.models import Word2Vec

from backend.lib.helpers import UserInput, convert_to_int
from backend.abstract.processor import BasicProcessor
from backend.lib.exceptions import ProcessorInterruptedException

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters", "Tom Willaert"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class GenerateWord2Vec(BasicProcessor):
	"""
	Generate Word2Vec models
	"""
	type = "generate-word2vec"  # job type ID
	category = "Text analysis"  # category
	title = "Generate Word2Vec models"  # title displayed in UI
	description = "Generates Word2Vec models for the sentences, per chosen time interval. These can then be used to analyse semantic word associations within the corpus."  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI

	accepts = ["tokenise-posts"]

	input = "zip"
	output = "zip"

	references = [
		"[Mikolov, Tomas, Ilya Sutskever, Kai Chen, Greg Corrado, and Jeffrey Dean. 2013. \"Distributed Representations of Words and Phrases and their Compositionality\". *Advances in Neural Information Processing Systems* 26.](http://papers.nips.cc/paper/5021-distributed-representations-of-words-and-phrases-and)"
		"[Ganesan, Kavita. \"Word2Vec: A Comparison Between CBOW, SkipGram & SkipGramSI\"](https://kavita-ganesan.com/comparison-between-cbow-skipgram-subword/#.X0O5-C1Y6M8)",
	]

	options = {
		"algorithm": {
			"type": UserInput.OPTION_CHOICE,
			"default": "cbow",
			"options": {
				"cbow": "Continuous Bag of Words (CBOW)",
				"skipgram": "Skip-gram"
			},
			"help": "Training algorithm",
			"tooltip": "See processor references for a more detailed explanation."
		},
		"window": {
			"type": UserInput.OPTION_TEXT,
			"min": 1,
			"max": 10,
			"default": 5,
			"help": "Window size",
			"tooltip": "Maximum distance between the current and predicted word within a sentence"
		},
		"negative": {
			"type": UserInput.OPTION_TOGGLE,
			"default": False,
			"help": "Use negative sampling"
		}
	}

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a number of files containing
		tokenised posts, grouped per time unit as specified in the parameters.
		"""
		self.dataset.update_status("Processing sentences")

		use_skipgram = 1 if self.parameters.get("algorithm") == "skipgram" else 0
		window = min(10, max(1, convert_to_int(self.parameters.get("window"))))
		use_negative = 5 if self.parameters.get("negative") else 0

		# prepare staging area
		temp_path = self.dataset.get_temporary_path()
		temp_path.mkdir()

		# go through all archived token sets and vectorise them
		models = 0
		with zipfile.ZipFile(self.source_file, "r") as token_archive:
			token_sets = token_archive.namelist()

			# create one model file per token file
			for token_set in token_sets:
				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while processing token sets")

				# the model file's name will be based on the token set name,
				# i.e. 2020-08-01.json becomes 2020-08-01.model
				token_set_name = token_set.split("/")[-1]

				# temporarily extract file (we cannot use ZipFile.open() as it doesn't support binary modes)
				temp_file = temp_path.joinpath(token_set_name)
				token_archive.extract(token_set_name, temp_path)

				# use the "list of lists" as input for the word2vec model
				# by default the tokeniser generates one list of tokens per
				# post... which may actually be preferable for short
				# 4chan-style posts. But alternatively it could generate one
				# list per sentence - this processor is agnostic in that regard
				self.dataset.update_status("Training model for token set %s..." % token_set_name)
				with temp_file.open() as input:
					model = Word2Vec(json.load(input), negative=use_negative, sg=use_skipgram, window=window)
					model_name = token_set_name.split(".")[0] + ".model"
					model.save(str(temp_path.joinpath(model_name)))
					models += 1

				temp_file.unlink()

		# create another archive with all model files in it
		with zipfile.ZipFile(self.dataset.get_results_path(), "w") as zip:
			for output_path in temp_path.glob("*.model"):
				zip.write(output_path, output_path.name)
				output_path.unlink()

		# delete temporary folder
		shutil.rmtree(temp_path)

		self.dataset.update_status("Finished")
		self.dataset.finish(models)

	def get_interval(self, item, interval):
		"""
		Get interval descriptor based on timestamp

		:param dict item:  Item to generate descriptor for, should have a
		"timestamp" key
		:param str interval:  Interval, one of "overall", "year", "month",
		"week", "day"
		:return str:  Interval descriptor, e.g. "overall", "2020", "2020-08",
		"2020-43", "2020-08-01"
		"""
		if interval == "overall":
			return interval

		if "timestamp" not in item:
			return "invalid_date"

		try:
			timestamp = datetime.datetime.strptime(item["timestamp"], "%Y-%m-%d %H:%M:%S")
		except (ValueError, TypeError) as e:
			return "invalid_date"

		if interval == "year":
			return str(timestamp.year)
		elif interval == "month":
			return str(timestamp.year) + "-" + str(timestamp.month)
		elif interval == "week":
			return str(timestamp.isocalendar()[0]) + "-" + str(timestamp.isocalendar()[1]).zfill(2)
		else:
			return str(timestamp.year) + "-" + str(timestamp.month) + "-" + str(timestamp.day)
