"""
Calculate word collocations from tokens
"""
import zipfile
import pickle
import shutil
import os
import itertools

import operator
from collections import OrderedDict, Counter
from nltk.collocations import *

from backend.lib.helpers import UserInput
from backend.abstract.postprocessor import BasicPostProcessor

class getCollocations(BasicPostProcessor):
	"""
	Generates word collocations from input tokens
	"""
	type = "collocations"  # job type ID
	category = "Text analysis"  # category
	title = "Word collocations"  # title displayed in UI
	description = "Extracts word collocations from as set of tokens."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	accepts = ["tokenise-posts"]  # query types this post-processor accepts as input

	# Parameters
	options = {
		"n_size": {
			"type": UserInput.OPTION_CHOICE,
			"default": 2,
			"options": {
				"2": "2 (~ bigrams)",
				"3": "3 (~ trigrams)"},
			"help": "N-size - How many words to generate collocations for"
		},
		"window_size": {
			"type": UserInput.OPTION_CHOICE,
			"default": "3",
			"options": {"3": "3", "4": "4", "5": "5", "6": "6"},
			"help": "Window size"
		},
		"query_string": {
			"type": UserInput.OPTION_TEXT,
			"default": "",
			"help": "Required words (comma-separated)"
		},
		"forbidden_words": {
			"type": UserInput.OPTION_TEXT,
			"default": "",
			"help": "Words to exclude (comma-separated)"
		},
		"max_output": {
			"type": UserInput.OPTION_TEXT,
			"default": "25",
			"min": 1,
			"max": 100,
			"help": "Number of results"
		}
	}

	def process(self):
		"""
		Unzips token sets, vectorises them and zips them again.
		"""


		# Validate and process user inputs
		n_size = int(self.parameters["n_size"])
		window_size = int(self.parameters["window_size"])
		query_string = self.parameters["query_string"].replace(" ", "")
		max_output = int(self.parameters["max_output"])
		if query_string != "":
			query_string = query_string.lower().split(',')
		else:
			query_string = False
		if self.parameters["forbidden_words"] != "":
			forbidden_words = self.parameters["forbidden_words"].replace(" ", "").lower().split(',')
		else:
			forbidden_words = False

		# Get token sets
		self.query.update_status("Processing token sets")
		dirname = self.query.get_results_path().replace(".", "")

		# Dictionary to save queries from
		results = []

		# Go through all archived token sets and generate collocations for each
		with zipfile.ZipFile(self.source_file, "r") as token_archive:
			token_sets = token_archive.namelist()
			index = 0

			# Loop through the tokens (can also be a single set)
			for tokens_name in token_sets:
				# temporarily extract file (we cannot use ZipFile.open() as it doesn't support binary modes)
				temp_path = dirname + "/" + tokens_name
				token_archive.extract(tokens_name, dirname)
				with open(temp_path, "rb") as binary_tokens:
					# these were saved as pickle dumps so we need the binary mode
					tokens = pickle.load(binary_tokens)
				os.unlink(temp_path)

				# Get the date
				date_string = tokens_name.split('.')[0]
				
				# Get the collocations. Returns a tuple.
				self.query.update_status("Generating collocations for " + date_string)
				collocations = self.get_collocations(tokens, window_size, n_size, query_string=query_string, max_output=max_output, forbidden_words=forbidden_words)

				# Loop through the results and store them in the results list
				for tpl in collocations:
					result = {}
					result['text'] = ' '.join(tpl[0])
					result['value'] = tpl[1]
					result['date'] = date_string
					results.append(result)

		if not results:
			return

		# Generate csv and finish
		self.query.update_status("Writing to csv and finishing")				
		self.query.write_csv_and_finish(results)

	def get_collocations(self, tokens, window_size, n_size, query_string=False, max_output=25, forbidden_words=False):
		""" Generates a tuple of word collocations (bigrams or trigrams).
		:param li tokens			list of tokens
		:param int window_size 		size of word window (context) to calculate the ngrams from
		:param int n_size			n-gram size. 1=unigrams, 2=bigrams, 3=trigrams
		:param str query_string		if given, only return collocations with this word.
									If emtpy, generates collocations for the overall corpus.
		:param int max_output 		the maximum amount of ngrams to return
		:param str forbidden_words	possible list of words to exclude from the results

		:return: list of tuples with collocations 
		
		"""

		# Two-word collocations (~ bigrams)
		if n_size == 2:
			finder = BigramCollocationFinder.from_words(tokens, window_size=window_size)

			# Filter out combinations not containing the query string
			if query_string != False:
				word_filter = lambda w1, w2: not any(string in (w1, w2) for string in query_string)
				finder.apply_ngram_filter(word_filter)
				# Filter out two times the occurance of the same query string
				duplicate_filter = lambda w1, w2: (w1 in query_string and w2 in query_string)
				finder.apply_ngram_filter(duplicate_filter)
			
			# Filter out forbidden words
			if forbidden_words != False:
				forbidden_words_filter = lambda w1, w2: any(string in (w1, w2) for string in forbidden_words)
				finder.apply_ngram_filter(forbidden_words_filter)

			#finder.apply_freq_filter(min_frequency)

		# Three-word collocations (~ trigrams)
		elif n_size == 3:
			finder = TrigramCollocationFinder.from_words(tokens, window_size=window_size)

			# Filter out combinations not containing the query string
			if query_string != False:
				word_filter = lambda w1, w2, w3: not any(string in (w1, w2, w3) for string in query_string)
				finder.apply_ngram_filter(word_filter)
			
			# Filter out forbidden words
			if forbidden_words != False:
				forbidden_words_filter = word_filter = lambda w1, w2, w3: any(string in (w1, w2, w3) for string in forbidden_words)
				finder.apply_ngram_filter(word_filter)

			#finder.apply_freq_filter(min_frequency)

		else:
			return "n_size is not valid. Use 1 or 2"

		colocations = sorted(finder.ngram_fd.items(), key=operator.itemgetter(1), reverse=True)[0:max_output]
		return colocations