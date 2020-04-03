"""
Create a word embedding model of tokenised strings.
"""
import pickle
import zipfile
import shutil

from gensim.models import Word2Vec, Phrases
from pathlib import Path

from backend.lib.helpers import UserInput
from backend.abstract.processor import BasicProcessor

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

class word_embeddings(BasicProcessor):
	"""
	Generate a word embedding model from tokenised text.
	"""

	type = "word-embeddings"  # job type ID
	category = "Text analysis"  # category
	title = "Word embeddings"  # title displayed in UI
	description = "Generate a word embedding model from the tokenised text. Note: good models require a lot of data."  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI
	accepts = ["tokenise-posts"]  # query types this post-processor accepts as input

	input = "zip"
	output = "zip"

	options = {
		"model_type": {
			"type": UserInput.OPTION_CHOICE,
			"default": "word2vec (Mikolov et al. 2013)",
			"options": {
				"word2vec": "word2vec"
			},
			"help": "Model type"
		},
		"algorithm": {
			"type": UserInput.OPTION_CHOICE,
			"default": "skip-gram",
			"options": {
				"skip-gram": "skip-gram",
				"cbow": "cbow"
			},
			"help": "Training algorithm"
		},
		"window": {
			"type": UserInput.OPTION_CHOICE,
			"default": 5,
			"options": {"3": 3, "4": 4, "5": 5, "6": 6, "7": 7},
			"help": "Maximum distance between the current and predicted word within a sentence"
		},
		"dimensions": {
			"type": UserInput.OPTION_TEXT,
			"default": 100,
			"help": "Dimensionality of the word vectors"
		},
		"min_count": {
			"type": UserInput.OPTION_TEXT,
			"default": 1,
			"help": "The minimum of how often a word should occur in the corpus"
		}
	}

	def process(self):
		"""
		Unzips and makes tokens for all datasets
		"""

		min_rows = 10000

		# prepare staging area
		tmp_path = self.dataset.get_temporary_path()
		tmp_path.mkdir()

		# Get token sets
		self.dataset.update_status("Processing token sets")
		tokens = []
		finished_models = 0

		results_path = self.dataset.get_results_path()
		dirname = Path(results_path.parent, results_path.name.replace(".", ""))

		# Go through all archived token sets and a model for each
		with zipfile.ZipFile(self.source_file, "r") as token_archive:
			token_sets = token_archive.namelist()
			index = 0

			# Loop through the tokens (can also be a single set)
			for tokens_name in token_sets:
				# stop processing if worker has been asked to stop
				if self.interrupted:
					raise ProcessorInterruptedException

				# temporarily extract file (we cannot use ZipFile.open() as it doesn't support binary modes)
				temp_path = dirname.joinpath(tokens_name)
				token_archive.extract(tokens_name, dirname)
				with temp_path.open("rb") as binary_tokens:

					# these were saved as pickle dumps so we need the binary mode
					tokens = pickle.load(binary_tokens)

				temp_path.unlink()

				# Get the date
				date_string = tokens_name.split('.')[0]

				# Train the model(s)
				self.dataset.update_status("Generating model for " + date_string)
				
				# word2vec - more types to follow
				if self.parameters.get("model_type") == "word2vec":
					if tokens:

						# Train that datar!
						model = self.train_w2v_model(tokens)
						
						# Too token datasets with too little data (< 10 posts) will be skipped
						if model:
							# Store the model as KeyedVectors - we don't need to resume training later.
							model.wv.save(str(tmp_path.joinpath(date_string + ".model")))
							finished_models += 1

		# Zip the whole lot of them
		self.dataset.update_status("Compressing results into archive")
		with zipfile.ZipFile(self.dataset.get_results_path(), "w") as zip:

			# Loop through all the files
			for file in tmp_path.glob("*"):
				
				# Zip a model and delete the original file
				zip.write(file, file.name)
				tmp_path.joinpath(file).unlink()

		# delete temporary files and folder
		shutil.rmtree(tmp_path)

		# Finish
		self.dataset.finish(finished_models)

	def train_w2v_model(self, tokens, min_word=0):
		"""
		Trains a w2v model. Input must be a list of strings.
		
		:param tokens, list: 	List of tokens to train on.
		:param modelname		Name of the saved model
		:param min_word			The minimum amount of occurances of words to be included in the model. Useful for filtering out bloat.
		
		"""
		
		# This makes sure that frequent bigrams are treated as a single vector
		bigram_transformer = Phrases(tokens)
		
		# Set parameters

		# Set min count
		try:
			min_count = int(self.parameters.get("min_count"))
		except ValueError:
			min_count = 10

		# Set window size
		try:
			window_size = int(self.parameters.get("window"))
		except ValueError:
			window_size = 5
		
		# Set correct value for training algorithms
		if self.parameters.get("algorithm") == "skip-gram":
			sg = 0
		elif self.parameters.get("algorithm") == "cbow":
			sg = 1
		else:
			sg = 0

		# Skip tokenset with less than a thousand posts
		if len(tokens) < 1000:
			return None

		# Train the model!
		else:
			model = Word2Vec(bigram_transformer[tokens], min_count=min_count, window=window_size, sg=sg, workers=4)

		return model