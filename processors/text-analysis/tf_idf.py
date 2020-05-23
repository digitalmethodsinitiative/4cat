"""
Create a csv with tf-idf ranked terms
"""
import json
import pickle
import zipfile
import numpy as np
import pandas as pd
import itertools

from pathlib import Path

from backend.lib.helpers import UserInput, convert_to_int
from backend.lib.exceptions import ProcessorInterruptedException
from backend.abstract.processor import BasicProcessor

from sklearn.feature_extraction.text import TfidfVectorizer
from gensim.models import TfidfModel
from gensim import corpora

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

class DisabledTfIdf(): #BasicProcessor):
	"""
	
	Get tf-idf terms

	"""
	type = "tfidf"  # job type ID
	category = "Text analysis"  # category
	title = "Tf-idf"  # title displayed in UI
	description = "Get the tf-idf values of tokenised text. Works better with more documents (e.g. day-separated)."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI
	accepts = ["tokenise-posts"]  # query types this post-processor accepts as input

	input = "zip"
	output = "csv:text,value,date"

	options = {
		"library": {
			"type": UserInput.OPTION_CHOICE,
			"default": "scikit-learn",
			"options": {"scikit-learn": "scikit-learn", "gensim": "gensim"},
			"help": "Library",
			"tooltip": "Which Python library should do the calculations? Gensim is better in optimising memory, so should be used for large datasets. Check the documentation in this module's references."
		},
		"max_output": {
			"type": UserInput.OPTION_TEXT,
			"default": 10,
			"min": 1,
			"max": 100,
			"help": "Words to return per timeframe"
		},
		"min_occurrences": {
			"type": UserInput.OPTION_TEXT,
			"default": "",
			"min": 1,
			"max": 10000,
			"help": "[scikit-learn] Ignore terms that appear in less than this amount of token sets",
			"tooltip": "Useful for filtering out very sporadic terms."
		},
		"max_occurrences": {
			"type": UserInput.OPTION_TEXT,
			"default": "",
			"min": 1,
			"max": 10000,
			"help": "[scikit-learn] Ignore terms that appear in more than this amount of token sets",
			"tooltip": "Useful for getting rarer terms not consistent troughout the dataset. Leave empty if terms may appear in all sets."
		},
		"n_size": {
			"type": UserInput.OPTION_CHOICE,
			"default": "",
			"options": {"1": 1, "2": 2},
			"help": "[scikit-learn] Amount of words to return (1 = unigrams, 2 = bigrams)"
		},
		"smartirs": {
			"type": UserInput.OPTION_TEXT,
			"default": "nfc",
			"help": "[gensim] SMART parameters",
			"tooltip": "SMART is a mnemonic notation type for various tf-idf parameters. Check this module's references for more information."
		}
	}

	references = [
		"[Spärck Jones, Karen. 1972. \"A statistical interpretation of term specificity and its application in retrieval.\" *Journal of Documentation* (28), 1: 11–21.](http://citeseerx.ist.psu.edu/viewdoc/download?doi=10.1.1.115.8343&rep=rep1&type=pdf)",
		"[Robertson, Stephen. 2004. \"Understanding Inverse Document value: On Theoretical arguments for IDF.\" *Journal of Documentation* (60), 5: 503–520](http://citeseerx.ist.psu.edu/viewdoc/download?doi=10.1.1.438.2284&rep=rep1&type=pdf)",
		"[Spärck Jones, Karen. 2004. \"IDF term weighting and IR research lessons\". *Journal of Communication* (60), 5: 521-523.](https://www.staff.city.ac.uk/~sb317/idfpapers/ksj_reply.pdf)",
		"[Gensim tf-idf documentation.](https://radimrehurek.com/gensim/models/tfidfmodel.html)",
		"[Scikit learn tf-idf documentation.](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html)",
		"[Tf-idf - Wikipedia.](https://en.wikipedia.org/wiki/Tf%E2%80%93idf)",
		"[What is tf-idf? - William Scott](https://towardsdatascience.com/tf-idf-for-document-ranking-from-scratch-in-python-on-real-world-dataset-796d339a4089)",
		"[SMART Information Retrieval System](https://en.wikipedia.org/wiki/SMART_Information_Retrieval_System)"
	]


	def process(self):
		"""
		Unzips and appends tokens to fetch and write a tf-idf matrix
		"""

		# Validate and process user inputs - parse to int
		library = self.parameters.get("library", "gensim")
		n_size = convert_to_int(self.parameters.get("n_size", 1), 1)
		min_occurrences = convert_to_int(self.parameters.get("min_occurrences", 1), 1)
		max_occurrences = convert_to_int(self.parameters.get("min_occurrences", -1), -1)
		max_output = convert_to_int(self.parameters.get("max_output", 10), 10)
		smartirs = self.parameters.get("smartirs", "nfc")

		# Get token sets
		self.dataset.update_status("Processing token sets")
		tokens = []
		dates = []

		results_path = self.dataset.get_results_path()
		dirname = Path(results_path.parent, results_path.name.replace(".", ""))

		# Go through all archived token sets and generate collocations for each
		with zipfile.ZipFile(str(self.source_file), "r") as token_archive:
			token_sets = token_archive.namelist()
			index = 0

			# Loop through the tokens (can also be a single set)
			for tokens_name in token_sets:
				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while loading token sets")

				# Get the date
				date_string = tokens_name.split('.')[0]
				dates.append(date_string)

				# Temporarily extract file (we cannot use ZipFile.open() as it doesn't support binary modes)
				temp_path = dirname.joinpath(tokens_name)
				token_archive.extract(str(tokens_name), str(dirname))

				# we support both pickle and json dumps of vectors
				token_unpacker = pickle if tokens_name.split(".")[-1] == "pb" else json

				with temp_path.open("rb") as binary_tokens:

					# these were saved as pickle dumps so we need the binary mode
					post_tokens = token_unpacker.load(binary_tokens)
	
					# Flatten the list of list of tokens - we're treating the whole time series as one document.
					post_tokens = list(itertools.chain.from_iterable(post_tokens))

					# Add to all date's tokens
					tokens.append(post_tokens)

				temp_path.unlink()

		# Make sure `min_occurrences` and `max_occurrences` are valid
		if min_occurrences > len(tokens):
			min_occurrences = len(tokens) - 1
		if max_occurrences <= 0 or max_occurrences > len(tokens):
			max_occurrences = len(tokens)

		# Get the tf-idf matrix.
		self.dataset.update_status("Generating tf-idf for token set")
		try:

			if library == "gensim":
				results = self.get_tfidf_gensim(tokens, dates, top_n=max_output, smartirs=smartirs)
			elif library == "scikit-learn":
				results = self.get_tfidf_sklearn(tokens, dates, ngram_range=n_size, min_occurrences=min_occurrences,
								 max_occurrences=max_occurrences, top_n=max_output)
			else:
				self.dataset.update_status("Invalid library.")
				self.dataset.finish(0)
				return

			if results:
				# Generate csv and finish
				self.dataset.update_status("Writing to csv and finishing")
				self.write_csv_items_and_finish(results)

		except MemoryError:
			self.dataset.update_status("Out of memory - dataset too large to run tf-idf analysis.")
			self.dataset.finish(0)

	def get_tfidf_gensim(self, tokens, dates, top_n=25, smartirs="nfc"):
		"""
		Creates a csv with the top n highest scoring tf-idf words.

		:param input, list:			List of tokens.
		:param dates, list:			List of dates.
		:param top_n, int:			The amount of top weighted tf-idf terms to return per date.
		:param smartirs, str:		Parameters for SMART Information Retrieval System.

		:returns dict, results
		"""

		# Create a bag of words with words repsented as ints.
		self.dataset.update_status("Converting corpus to bag of words")
		dict_tokens = corpora.Dictionary()
		corpus = [dict_tokens.doc2bow(doc, allow_update=True) for doc in tokens]

		# Calculate the tf-idf
		self.dataset.update_status("Vectorizing")
		try:
			tfidf_model = TfidfModel(corpus, smartirs=smartirs)
		except ValueError:
			self.dataset.update_status("Invalid SMART string")
			return

		# Retrieve the words and their tf-idf weights.
		vector = tfidf_model[corpus]

		data = []
		row = []
		col = []
		vocab = []

		results = []

		self.dataset.update_status("Extracting results")
		for i, doc in enumerate(vector):
			doc_results = [[dict_tokens[id], freq] for id, freq in doc]
			doc_results.sort(key = lambda x: x[1], reverse=True) # Sort on score
			
			for word, score in doc_results[:top_n]:
				result = {}
				result["item"] = word
				result["value"] = score
				result["date"] = dates[i]
				results.append(result)

		return results

	def get_tfidf_sklearn(self, tokens, dates, ngram_range=1, min_occurrences=0, max_occurrences=0, top_n=25):
		"""
		Creates a csv with the top n highest scoring tf-idf words using sklearn's TfIdfVectoriser.

		:param tokens, list:			List of tokens. Should be unpickled first
		:param dates, list:				List of column names.
		:param max_occurrences, int:	Filter out words that appear in more than length of token list - max_occurrences.
		:param min_occurrences, int:	Filter out words that appear in less than min_occurrences.
		:param ngram_range, tuple:		The amount of words to extract.
		:param top_n, int:				The amount of top weighted tf-idf terms to return per date.

		:returns dict, results
		"""

		# Convert to tuple
		ngram_range = (int(ngram_range), int(ngram_range))
		
		# Vectorise
		self.dataset.update_status("Vectorizing")
		tfidf_vectorizer = TfidfVectorizer(min_df=min_occurrences, max_df=max_occurrences, ngram_range=ngram_range,
										   analyzer="word", token_pattern=None, tokenizer=lambda i: i, lowercase=False)
		tfidf_matrix = tfidf_vectorizer.fit_transform(tokens)

		feature_array = np.array(tfidf_vectorizer.get_feature_names())
		tfidf_sorting = np.argsort(tfidf_matrix.toarray()).flatten()[::-1]

		# Print and store top n highest scoring tf-idf scores
		top_words = feature_array[tfidf_sorting][:top_n]
		weights = np.asarray(tfidf_matrix.mean(axis=0)).ravel().tolist()
		df_weights = pd.DataFrame({"term": tfidf_vectorizer.get_feature_names(), "weight": weights})
		df_weights = df_weights.sort_values(by="weight", ascending=False).head(100)

		self.dataset.update_status("Writing tf-idf vector to csv")
		df_matrix = pd.DataFrame(tfidf_matrix.toarray(), columns=tfidf_vectorizer.get_feature_names())

		# Turn the dataframe 90 degrees
		df_matrix = df_matrix.transpose()

		# Do some editing of the dataframe
		df_matrix.columns = dates
		cols = df_matrix.columns.tolist()
		cols = dates
		df_matrix = df_matrix[cols]

		# Store each terms per document as a dict, store these in a list, and return
		results = []
		for index, document in enumerate(df_matrix):
			df_tim = (df_matrix.sort_values(by=[document], ascending=False))[:top_n]
			for i in range(top_n):
				result = {}
				result["item"] = df_tim.index.values[i]
				result["value"] = df_tim[document].values[i].tolist()
				result["date"] = document
				results.append(result)
		return results
