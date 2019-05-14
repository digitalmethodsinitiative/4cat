"""
Create a csv with tf-idf ranked terms
"""
import os
import pickle
import zipfile
import shutil
import numpy as np
import pandas as pd

from backend.lib.helpers import UserInput
from backend.abstract.postprocessor import BasicPostProcessor

from collections import OrderedDict
from csv import DictReader
from sklearn.feature_extraction.text import TfidfVectorizer

import config

class tfIdf(BasicPostProcessor):
	"""
	
	Get tf-idf terms

	"""
	type = "tfidf"  # job type ID
	category = "Text analysis"  # category
	title = "Tf-idf"  # title displayed in UI
	description = "Get the tf-idf values of tokenised text. Works better with more documents (e.g. day-separated)."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI
	accepts = ["tokenise-posts"]  # query types this post-processor accepts as input

	options = {
		"n_size": {
			"type": UserInput.OPTION_CHOICE,
			"default": 1,
			"options": {"1": 1, "2": 2},
			"help": "Amount of words to return (tf-idf unigrams or bigrams)"
		},
		"min_df": {
			"type": UserInput.OPTION_TEXT,
			"default": 1,
			"min": 1,
			"max": 10000,
			"help": "The minimum amount of days/months/years a term should appear in. Useful for filtering out very sporadic terms."
		},
		"max_df": {
			"type": UserInput.OPTION_TEXT,
			"default": "",
			"min": 1,
			"max": 10000,
			"help": "The maximum amount of days/months/years a term may appear in. Useful for fetching rare terms that are not constantly prevalent throughout dataset. Leave emtpy if terms may appear in all sets."
		},
		"max_output": {
			"type": UserInput.OPTION_TEXT,
			"default": 10,
			"min": 1,
			"max": 100,
			"help": "Output number - The amount of words to return per timeframe"
		}
	}
	
	def process(self):
		"""
		Unzips and appends tokens to fetch and write a tf-idf matrix
		"""

		# Validate and process user inputs - parse to int
		n_size = (int(self.parameters["n_size"]),int(self.parameters["n_size"]))
		min_df = int(self.parameters["min_df"])
		max_df = self.parameters["min_df"]
		if max_df != "":
			max_df = int(self.parameters["max_df"])
		max_output = int(self.parameters["max_output"])

		# Get token sets
		self.query.update_status("Processing token sets")
		tokens = []
		dates = []
		dirname = self.query.get_results_path().replace(".", "")

		# Go through all archived token sets and generate collocations for each
		with zipfile.ZipFile(self.source_file, "r") as token_archive:
			token_sets = token_archive.namelist()
			index = 0

			# Loop through the tokens (can also be a single set)
			for tokens_name in token_sets:
				
				# Get the date
				date_string = tokens_name.split('.')[0]
				dates.append(date_string)
				# Temporarily extract file (we cannot use ZipFile.open() as it doesn't support binary modes)
				temp_path = dirname + "/" + tokens_name
				token_archive.extract(tokens_name, dirname)
				with open(temp_path, "rb") as binary_tokens:
					# these were saved as pickle dumps so we need the binary mode
					tokens.append(pickle.load(binary_tokens))
				os.unlink(temp_path)

		# Make sure `min_df` and `max_df` are valid
		if min_df == 0:
			min_df = 1
		elif min_df > len(tokens):
			min_df = len(tokens) - 1
		if max_df == 0 or max_df == "" or max_df > len(tokens):
			max_df = len(tokens)
		else:
			max_df = len(tokens) - max_df

		# Get the collocations. Returns a tuple.
		self.query.update_status("Generating tf-idf for token set")
		results = self.get_tfidf(tokens, dates, ngram_range=n_size, min_df=min_df, max_df=max_df, top_n=max_output)

		# Generate csv and finish
		self.query.update_status("Writing to csv and finishing")
		self.query.write_csv_and_finish(results)

	def get_tfidf(self, tokens, dates, ngram_range=1, min_df=0, max_df=0, top_n=25):
		'''
		Creates a csv with the top n highest scoring tf-idf words.

		:param tokens list,			list of tokens. Should be unpickled first
		:param dates list,		list of column names  
		:param max_df int,			filter out words that appear in more than length of token list - max_df
		:param min_df int,			filter out words that appear in less than min_df
		:param ngram_range tuple,	the amount of words to extract

		:returns ...
		'''

		# Vectorise
		self.query.update_status('Vectorizing')
		tfidf_vectorizer = TfidfVectorizer(min_df=min_df, max_df=max_df, ngram_range=ngram_range, analyzer='word', token_pattern=None, tokenizer=lambda i:i, lowercase=False)
		tfidf_matrix = tfidf_vectorizer.fit_transform(tokens)
		
		feature_array = np.array(tfidf_vectorizer.get_feature_names())
		tfidf_sorting = np.argsort(tfidf_matrix.toarray()).flatten()[::-1]
		
		# Print and store top n highest scoring tf-idf scores
		top_words = feature_array[tfidf_sorting][:top_n]
		weights = np.asarray(tfidf_matrix.mean(axis=0)).ravel().tolist()
		df_weights = pd.DataFrame({'term': tfidf_vectorizer.get_feature_names(), 'weight': weights})
		df_weights = df_weights.sort_values(by='weight', ascending=False).head(100)

		self.query.update_status('Writing tf-idf vector to csv')
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
				result['text'] = df_tim.index.values[i]
				result['value'] = df_tim[document].values[i].tolist()
				result['date'] = document
				results.append(result)
		return results