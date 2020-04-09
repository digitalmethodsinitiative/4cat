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

class word_embeddings_neighbours(BasicProcessor):
	"""
	Generate a word embedding model from tokenised text.
	"""

	type = "word-embeddings-neighbours"  # job type ID
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
		"cosine_threshold":
		{
			"type": UserInput.OPTION_TEXT,
			"default": 0.6,
			"options": {
				"cosine similarity threshold": ""
			},
			"help": "Only return words with a cosine similarity above this value (-1 to 1)."
		},
		"top_n": {
			"type": UserInput.OPTION_TEXT,
			"default": 50,
			"options": {
				"top": ""
			},
			"help": "The maximum amount of nearest neigbours to extract per word (max. 100)."
		},
		"crawl_depth": {
			"type": UserInput.OPTION_CHOICE,
			"default": 1,
			"options": {"1": 1, "2": 2, "3": 3},
			"help": "The crawl depth. 1 only gets the neighbours of the input word(s), 2 also their neighbours, etc."
		}
	}

	def process(self):
		"""
		Loads the models and outputs the n nearest neighbours
		"""

		# Extract text input
		check_words = self.parameters.get("words")
		if not check_words:
			self.dataset.update_status("No words to find nearest neighbours of were provided")
			self.dataset.finish(-1)
			return

		check_words = [word.strip() for word in check_words.split(",")]

		# Extract cosine threshold
		try:
			cosine_threshold = float(self.parameters.get("cosine_threshold"))
			if cosine_threshold > 1:
				cosine_threshold = 1
			if cosine_threshold < -1:
				cosine_threshold = -1
		except ValueError:
			self.dataset.update_status("Invalid number of  provided. Insert a number between -1 and 1, like 0.75")
			self.dataset.finish(-1)
			return

		# Extract top n
		try:
			top_n = int(self.parameters.get("top_n"))
			if top_n == 0:
				top_n = 10
			if top_n > 100: # Can't be more than a hundred
				top_n = 100
		except ValueError:
			self.dataset.update_status("Invalid number of nearest neighbours provided")
			self.dataset.finish(-1)
			return

		# Extract crawl depth
		crawl_depth = int(self.parameters.get("crawl_depth") or 1)
		if crawl_depth < 1 or crawl_depth > 3:
			crawl_depth = 1

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
				
				# Words to crawl
				crawl_words = check_words
				words_crawled = []

				# Temporarily extract file (we cannot use ZipFile.open() as it doesn't support binary modes)
				tmp_file_path = tmp_dir.joinpath(model_name)
				model_archive.extract(model_name, tmp_dir)

				# Check if there's also a vectors.npy file (for large models) in the folder, and if so, extract it
				if model_name + ".vectors.npy" in model_files:
					model_archive.extract(model_name + ".vectors.npy", tmp_dir)

				model = KeyedVectors.load(str(tmp_file_path), mmap="r")

				# Keep this loop going as long as we haven't reached the crawl limit.
				for i in range(crawl_depth):

					new_crawl_words = []

					# Check certain words in this model
					for word in crawl_words:

						# Get the nearest neigbours
						try:
							nearest_neighbours = model.wv.most_similar(positive=[word], topn=top_n)

						# If not in vocabulary
						except KeyError as e:	
							results.append({
								"source_word": word,
								"target_word": "ERROR: input word not in this model's vocabulary, be sure to insert lemmatized or stemmed versions",
								"weight": 0,
								"source_occurrences": 0,
								"target_occurrences": 0,
								"model": model_name,
								"date": date_string
							})
							continue

						# Get the nearest neigbours
						for nearest_neighbour in nearest_neighbours:
							if nearest_neighbour[1] >= cosine_threshold: # Cosine similarity threshold check
								results.append({
									"source_word": word,
									"target_word": nearest_neighbour[0],
									"weight": nearest_neighbour[1], # The edge weight
									"source_occurrences": model.vocab[word].count, # How often the source word appears in the model
									"target_occurrences": model.vocab[nearest_neighbour[0]].count, # How often the target word appears in the model
									"model": model_name,
									"date": date_string
								})

								# To check in possible next crawl
								if nearest_neighbour[0] not in words_crawled:
									new_crawl_words.append(nearest_neighbour[0])

					# After first crawl, prepare new words to check
					crawl_words = new_crawl_words

			# Delete the temporary folder
			shutil.rmtree(tmp_dir)

		if not results:
			return

		# Generate csv and finish
		self.dataset.update_status("Writing to csv and finishing")
		self.write_csv_items_and_finish(results)