"""
Create a word embedding model of tokenised strings.
"""
import zipfile
import shutil
from gensim.models import Word2Vec, KeyedVectors

from pathlib import Path

from backend.lib.helpers import UserInput
from backend.abstract.processor import BasicProcessor

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

class word_embeddings_neigbours(BasicProcessor):
	"""
	Generate a word embedding model from tokenised text.
	"""

	type = "word-embeddings-neigbours"  # job type ID
	category = "Text analysis"  # category
	title = "Word embeddings nearest neighbours"  # title displayed in UI
	description = "Output the nearest neighbours of words from a word embedding model."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI
	accepts = ["word-embeddings"]  # query types this post-processor accepts as input

	input = "zip"
	output = "csv"

	options = {
		"words": {
			"type": UserInput.OPTION_TEXT,
			"default": "",
			"options": {
				"words_input": ""
			},
			"help": "Words to check neighbours for, comma separated. Lemmatizing or stemming should be done manually"
		},
		"top_n": {
			"type": UserInput.OPTION_TEXT,
			"default": 10,
			"options": {
				"top": ""
			},
			"help": "How many nearest neigbours to extract."
		}
	}

	def process(self):
		"""
		Loads the models and outputs the n nearest neighbours
		"""

		# Extract text input
		check_words = self.parameters.get("words")
		if not check_words:
			self.dataset.update_status("No text inserted")
			self.dataset.finish(0)
		check_words = [word.strip() for word in check_words.split(",")]

		# Extract top n
		try:
			top_n = int(self.parameters.get("top_n"))
			if top_n == 0:
				top_n = 10
		except ValueError:
			self.dataset.update_status("No valid top_n inserted")
			self.dataset.finish(0)

		results = []
		results_path = self.dataset.get_results_path()
		tmp_dir = self.dataset.get_temporary_path()

		# Go through all archived token sets and generate collocations for each
		with zipfile.ZipFile(str(self.source_file), "r") as model_archive:
			
			# Get the filenames and only keep those containing the model (so e.g. no vectors.npy files)
			model_files = model_archive.namelist()
			model_names = [model_name for model_name in model_files if model_name.endswith(".model")]
			
			if not model_names:
				return

			# Extract the models and output nearest neighbour(s)
			for model_name in model_names:

				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while loading token sets")

				# Get the date
				date_string = model_name.split('.')[0]
				
				# Temporarily extract file (we cannot use ZipFile.open() as it doesn't support binary modes)
				tmp_file_path = tmp_dir.joinpath(model_name)
				model_archive.extract(model_name, tmp_dir)

				# Check if there's also a vectors.npy file (for large models) in the folder, and if so, extract it
				if model_name + ".vectors.npy" in model_files:
					model_archive.extract(model_name + ".vectors.npy", tmp_dir)

				model = KeyedVectors.load(str(tmp_file_path), mmap="r")

				# Check all words in this model
				for check_word in check_words:

					# Get the nearest neigbours
					try:
						nearest_neighbours = model.wv.most_similar(positive=[check_word], topn=top_n)
					
					# If not in vocabulary
					except KeyError as e:	
						results.append({
							"input_word": check_word,
							"nearest_neighbour": "ERROR: input word not in this model's vocabulary, be sure to insert lemmatized or stemmed versions",
							"cosine_similarity": 0,
							"model": model_name,
							"date": date_string
						})
						continue

					# Get the nearest neigbours
					for nearest_neighbour in nearest_neighbours:
						results.append({
							"input_word": check_word,
							"nearest_neighbour": nearest_neighbour[0],
							"cosine_similarity": nearest_neighbour[1],
							"model": model_name,
							"date": date_string
						})

			# Delete the temporary folder
			shutil.rmtree(tmp_dir)

		if not results:
			return

		# Generate csv and finish
		self.dataset.update_status("Writing to csv and finishing")
		self.write_csv_items_and_finish(results)