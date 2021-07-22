"""
Generate interval-based word embedding models for sentences
"""
import shutil
import pickle
import json

from gensim.models import Word2Vec, FastText
from gensim.models.phrases import Phrases, Phraser
from pathlib import Path

from common.lib.helpers import UserInput, convert_to_int
from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen", "Stijn Peeters", "Tom Willaert"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


class GenerateWordEmbeddings(BasicProcessor):
	"""
	Generate Word Embeddings
	"""
	type = "generate-embeddings"  # job type ID
	category = "Text analysis"  # category
	title = "Generate Word Embedding Models"  # title displayed in UI
	description = "Generates Word2Vec or FastText word embedding models for the sentences, per chosen time interval. These can then be used to analyse semantic word associations within the corpus. Note that good models require large(r) datasets."  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI

	references = [
		"Word2Vec: [Mikolov, Tomas, Ilya Sutskever, Kai Chen, Greg Corrado, and Jeffrey Dean. 2013. “Distributed Representations of Words and Phrases and Their Compositionality.” 8Advances in Neural Information Processing Systems*, 2013: 3111-3119.](https://papers.nips.cc/paper/5021-distributed-representations-of-words-and-phrases-and-their-compositionality.pdf)",
		"Word2Vec: [Mikolov, Tomas, Kai Chen, Greg Corrado, and Jeffrey Dean. 2013. “Efficient Estimation of Word Representations in Vector Space.” *ICLR Workshop Papers*, 2013: 1-12.](https://arxiv.org/pdf/1301.3781.pdf)",
		"Word2Vec: [A Beginner's Guide to Word Embedding with Gensim Word2Vec Model - Towards Data Science](https://towardsdatascience.com/a-beginners-guide-to-word-embedding-with-gensim-word2vec-model-5970fa56cc92)",
		"FastText: [Bojanowski, P., Grave, E., Joulin, A., & Mikolov, T. (2017). Enriching word vectors with subword information. *Transactions of the Association for Computational Linguistics*, 5, 135-146.](https://www.mitpressjournals.org/doi/abs/10.1162/tacl_a_00051)"
	]

	options = {
		"model-type": {
			"type": UserInput.OPTION_CHOICE,
			"default": "Word2Vec",
			"options": {
				"Word2Vec": "Word2Vec",
				"FastText": "FastText"
			},
			"help": "Model type"
		},
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
			"type": UserInput.OPTION_CHOICE,
			"default": "5",
			"options": {"3": 3, "4": 4, "5": 5, "6": 6, "7": 7},
			"help": "Window",
			"tooltip": "Maximum distance between the current and predicted word within a sentence"
		},
		"dimensionality": {
			"type": UserInput.OPTION_TEXT,
			"default": 100,
			"min": 50,
			"max": 1000,
			"help": "Dimensionality of the word vectors"
		},
		"min_count": {
			"type": UserInput.OPTION_TEXT,
			"default": 5,
			"help": "Minimum word occurrence",
			"tooltip": "How often a word should occur in the corpus to be included"
		},
		"max_words": {
			"type": UserInput.OPTION_TEXT,
			"default": 0,
			"min": 0,
			"help": "Retain top n words",
			"tooltip": "'0' retains all words, other values will discard less frequent words"
		},
		"negative": {
			"type": UserInput.OPTION_TOGGLE,
			"default": True,
			"help": "Use negative sampling"
		},
		"detect-bigrams": {
			"type": UserInput.OPTION_TOGGLE,
			"default": True,
			"help": "Detect bigrams",
			"tooltip": "If checked, commonly occurring word combinations ('New York') will be replaced with a single-word combination ('New_York')"
		}
	}

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor on token sets

		:param module: Dataset or processor to determine compatibility with
		"""
		return module.type == "tokenise-posts"

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a number of files containing
		tokenised posts, grouped per time unit as specified in the parameters.
		"""
		self.dataset.update_status("Processing sentences")

		use_skipgram = 1 if self.parameters.get("algorithm") == "skipgram" else 0
		window = min(10, max(1, convert_to_int(self.parameters.get("window"))))
		use_negative = 5 if self.parameters.get("negative") else 0
		min_count = max(1, convert_to_int(self.parameters.get("min_count")))
		dimensionality = convert_to_int(self.parameters.get("dimensionality"), 100)
		detect_bigrams = self.parameters.get("detect-bigrams")
		model_type = self.parameters.get("model-type")
		max_words = convert_to_int(self.parameters.get("max_words"))

		if max_words == 0:
			# unlimited amount of words in model
			max_words = None

		staging_area = self.dataset.get_staging_area()
		model_builder = {
			"Word2Vec": Word2Vec,
			"FastText": FastText
		}[model_type]

		# go through all archived token sets and vectorise them
		models = 0
		for temp_file in self.iterate_archive_contents(self.source_file):
			# use the "list of lists" as input for the word2vec model
			# by default the tokeniser generates one list of tokens per
			# post... which may actually be preferable for short
			# 4chan-style posts. But alternatively it could generate one
			# list per sentence - this processor is agnostic in that regard
			token_set_name = temp_file.name
			self.dataset.update_status("Extracting bigrams from token set %s..." % token_set_name)

			try:
				if detect_bigrams:
					bigram_transformer = Phrases(self.tokens_from_file(temp_file, staging_area))
					bigram_transformer = Phraser(bigram_transformer)
				else:
					bigram_transformer = None

				self.dataset.update_status("Training %s model for token set %s..." % (model_builder.__name__, token_set_name))
				try:
					model = model_builder(negative=use_negative, size=dimensionality, sg=use_skipgram, window=window, workers=3, min_count=min_count, max_final_vocab=max_words)

					# we do not simply pass a sentences argument to model builder
					# because we are using a generator, which exhausts, while
					# Word2Vec needs to iterate over the sentences twice
					# https://stackoverflow.com/a/57632747
					model.build_vocab(self.tokens_from_file(temp_file, staging_area, phraser=bigram_transformer))
					model.train(self.tokens_from_file(temp_file, staging_area, phraser=bigram_transformer), epochs=model.iter, total_examples=model.corpus_count)

				except RuntimeError as e:
					if "you must first build vocabulary before training the model" in str(e):
						# not enough data. Skip - if this happens for all models
						# an error will be generated later
						continue
					else:
						raise e

			except UnicodeDecodeError:
				self.dataset.update_status(
					"Error reading input data. If it was imported from outside 4CAT, make sure it is encoded as UTF-8.",
					is_final=True)
				self.dataset.finish(0)
				return

			# save - we only save the KeyedVectors for the model, this
			# saves space and we don't need to re-train the model later
			model_name = token_set_name.split(".")[0] + ".model"
			model.wv.save(str(staging_area.joinpath(model_name)))

			# save vocabulary too, some processors need it
			del model
			models += 1

		if models == 0:
			self.dataset.update_status("Not enough data in source file to train %s models." % model_builder.__name__)
			shutil.rmtree(staging_area)
			self.dataset.finish(0)
			return

		# create another archive with all model files in it
		self.dataset.update_status("%s model(s) saved." % model_builder.__name__)
		self.write_archive_and_finish(staging_area)

	def tokens_from_file(self, file, staging_area, phraser=None):
		"""
		Read tokens from token dump

		If the tokens were saved as JSON, take advantage of this and return
		them as a generator, reducing memory usage and allowing interruption.

		:param Path file:
		:param Path staging_area:  Path to staging area, so it can be cleaned
		up when the processor is interrupted
		:param Phraser phraser:  Optional. If given, the yielded sentence is
		passed through the phraser to detect (e.g.) bigrams.
		:return list:  A set of tokens
		"""

		if file.suffix == "pb":
			with file.open("rb") as input:
				return pickle.load(input)

		with file.open("r") as input:
			input.seek(1)
			while True:
				line = input.readline()
				if line is None:
					break

				if self.interrupted:
					shutil.rmtree(staging_area)
					raise ProcessorInterruptedException("Interrupted while reading tokens")

				if line == "]":
					# this marks the end of the file
					return

				try:
					# the tokeniser dumps the json with one set of tokens per
					# line, ending with a comma
					line = line.strip()
					if line[-1] == ",":
						line = line[:-1]
						
					token_set = json.loads(line)
					if phraser:
						yield phraser[token_set]
					else:
						yield token_set
				except json.JSONDecodeError:
					# old-format json dumps are not suitable for the generator
					# approach
					input.seek(0)
					everything = json.load(input)
					return everything
