"""
Create a csv with tf-idf ranked terms
"""
import pickle
import zipfile
import numpy as np
import pandas as pd

from pathlib import Path

from backend.lib.helpers import UserInput, convert_to_int
from backend.abstract.processor import BasicProcessor

from sklearn.feature_extraction.text import TfidfVectorizer

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

class tfIdf(BasicProcessor):
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
		"n_size": {
			"type": UserInput.OPTION_CHOICE,
			"default": 1,
			"options": {"1": 1, "2": 2},
			"help": "Amount of words to return (tf-idf unigrams or bigrams)"
		},
		"min_occurrences": {
			"type": UserInput.OPTION_TEXT,
			"default": 1,
			"min": 1,
			"max": 10000,
			"help": "Ignore terms that appear in less than this amount of token sets",
			"tooltip": "Useful for filtering out very sporadic terms."
		},
		"max_occurrences": {
			"type": UserInput.OPTION_TEXT,
			"default": "",
			"min": 1,
			"max": 10000,
			"help": "Ignore terms that appear in more than this amount of token sets",
			"tooltip": "Useful for getting rarer terms not consistent troughout the dataset. Leave empty if terms may appear in all sets."
		},
		"max_output": {
			"type": UserInput.OPTION_TEXT,
			"default": 10,
			"min": 1,
			"max": 100,
			"help": "Words to return per timeframe"
		}
	}

	def process(self):
		"""
		Unzips and appends tokens to fetch and write a tf-idf matrix
		"""

		# Validate and process user inputs - parse to int
		n_size = convert_to_int(self.parameters.get("n_size", 1), 1)
		n_size = (n_size, n_size)
		min_occurrences = convert_to_int(self.parameters.get("min_occurrences", 1), 1)
		max_occurrences = convert_to_int(self.parameters.get("min_occurrences", -1), -1)
		max_output = convert_to_int(self.parameters.get("max_output", 10), 10)

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
				# Get the date
				date_string = tokens_name.split('.')[0]
				dates.append(date_string)
				# Temporarily extract file (we cannot use ZipFile.open() as it doesn't support binary modes)
				temp_path = dirname.joinpath(tokens_name)
				token_archive.extract(str(tokens_name), str(dirname))
				with temp_path.open("rb") as binary_tokens:
					# these were saved as pickle dumps so we need the binary mode
					tokens.append(pickle.load(binary_tokens))
				temp_path.unlink()

		# Make sure `min_occurrences` and `max_occurrences` are valid
		if min_occurrences > len(tokens):
			min_occurrences = len(tokens) - 1
		if max_occurrences <= 0 or max_occurrences > len(tokens):
			max_occurrences = len(tokens)

		# Get the collocations. Returns a tuple.
		self.dataset.update_status("Generating tf-idf for token set")
		try:
			results = self.get_tfidf(tokens, dates, ngram_range=n_size, min_occurrences=min_occurrences,
								 max_occurrences=max_occurrences, top_n=max_output)
		except MemoryError:
			self.dataset.update_status("Out of memory - dataset to large to run tf-idf analysis.")
			self.dataset.finish(0)

		# Generate csv and finish
		self.dataset.update_status("Writing to csv and finishing")
		self.dataset.write_csv_and_finish(results)

	def get_tfidf(self, tokens, dates, ngram_range=(1,1), min_occurrences=0, max_occurrences=0, top_n=25):
		"""
		Creates a csv with the top n highest scoring tf-idf words.

		:param tokens list,			list of tokens. Should be unpickled first
		:param dates list,			list of column names  
		:param max_occurrences int,	filter out words that appear in more than length of token list - max_occurrences
		:param min_occurrences int,	filter out words that appear in less than min_occurrences
		:param ngram_range tuple,	the amount of words to extract

		:returns ...
		"""
		
		# Vectorise
		self.dataset.update_status('Vectorizing')
		tfidf_vectorizer = TfidfVectorizer(min_df=min_occurrences, max_df=max_occurrences, ngram_range=ngram_range,
										   analyzer='word', token_pattern=None, tokenizer=lambda i: i, lowercase=False)
		tfidf_matrix = tfidf_vectorizer.fit_transform(tokens)

		feature_array = np.array(tfidf_vectorizer.get_feature_names())
		tfidf_sorting = np.argsort(tfidf_matrix.toarray()).flatten()[::-1]

		# Print and store top n highest scoring tf-idf scores
		top_words = feature_array[tfidf_sorting][:top_n]
		weights = np.asarray(tfidf_matrix.mean(axis=0)).ravel().tolist()
		df_weights = pd.DataFrame({'term': tfidf_vectorizer.get_feature_names(), 'weight': weights})
		df_weights = df_weights.sort_values(by='weight', ascending=False).head(100)

		self.dataset.update_status('Writing tf-idf vector to csv')
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
				result['item'] = df_tim.index.values[i]
				result['frequency'] = df_tim[document].values[i].tolist()
				result['date'] = document
				results.append(result)
		return results
