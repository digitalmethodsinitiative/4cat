"""
Calculate word collocations from tokens
"""
import json
import pickle

from pathlib import Path

import operator
from nltk.collocations import *

from common.lib.helpers import UserInput
from backend.abstract.processor import BasicProcessor

class GetCollocations(BasicProcessor):
	"""
	Generates word collocations from input tokens
	"""
	type = "collocations"  # job type ID
	category = "Text analysis"  # category
	title = "Word collocations"  # title displayed in UI
	description = "Extracts word collocations from a set of tokens."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor on token sets

		:param module: Dataset or processor to determine compatibility with
		"""
		return module.type == "tokenise-posts"

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
			"default": "2",
			"options": {"2": "2", "3": "3", "4": "4", "5": "5", "6": "6"},
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
		"sort_words": {
			"type": UserInput.OPTION_TOGGLE,
			"default": False,
			"help": "Sort collocations alphabetically",
			"tooltip": "Selecting this will sort words so that \"dog bark\" and \"bark dog\" will result in the latter, and be counted as one. Usually, word order is relevant data, so this is turned off by default."
		},
		"min_frequency": {
			"type": UserInput.OPTION_TEXT,
			"default": 0,
			"help": "Minimum frequency of words appearing together"
		},
		"max_output": {
			"type": UserInput.OPTION_TEXT,
			"default": 0,
			"help": "Max. number of results per token set. 0 for unlimited"
		}
	}

	def process(self):
		"""
		Unzips token sets, vectorises them and zips them again.
		"""

		# Validate and process user inputs
		try:
			n_size = int(self.parameters.get("n_size", 2))
		except (ValueError, TypeError) as e:
			n_size = 2

		try:
			window_size = int(self.parameters.get("window_size", 2))
		except (ValueError, TypeError) as e:
			window_size = 2

		try:
			max_output = int(self.parameters.get("max_output", 0))
		except (ValueError, TypeError) as e:
			max_output = 0

		min_frequency = self.parameters.get("min_frequency")
		try:
			min_frequency = int(self.parameters.get("min_frequency", 0))
		except (ValueError, TypeError) as e:
			min_frequency = 0
		 
		query_string = self.parameters.get("query_string", "").replace(" ", "")

		# n_size smaller than window_size does not make sense
		n_size = min(n_size, window_size)
		
		if query_string != "":
			query_string = query_string.lower().split(',')
		else:
			query_string = False
		if self.parameters.get("forbidden_words", None):
			forbidden_words = self.parameters["forbidden_words"].replace(" ", "").lower().split(',')
		else:
			forbidden_words = False

		sort_words = self.parameters.get("sort_words", False)

		# Get token sets
		self.dataset.update_status("Processing token sets")
		dirname = Path(self.dataset.get_results_path().parent, self.dataset.get_results_path().name.replace(".", ""))

		# Dictionary to save queries from
		results = []

		# Go through all archived token sets and generate collocations for each
		for token_file in self.iterate_archive_contents(self.source_file):
			# we support both pickle and json dumps of vectors
			token_unpacker = pickle if token_file.suffix == "pb" else json

			with token_file.open("rb") as binary_tokens:
				tokens = token_unpacker.load(binary_tokens)

			# Get the date
			date_string = token_file.stem

			# Get the collocations. Returns a tuple.
			self.dataset.update_status("Generating collocations for " + date_string)

			# Store all the collocations from this tokenset here.
			collocations = []

			# The tokens are separated per posts, so we get collocations per post.
			for post_tokens in tokens:
				post_collocations = self.get_collocations(post_tokens, window_size, n_size, min_frequency=min_frequency,
														  query_string=query_string, forbidden_words=forbidden_words)
				collocations += post_collocations

			# Loop through the collocation per post, merge, and store in the results list
			tokenset_results = {}

			for tpl in collocations:

				collocation = tpl[0]

				# Sort the words, if indicated.
				# This can be handy to get rid of (almost) duplicate data.
				if sort_words:
					collocation = sorted(collocation)

				collocation = " ".join(collocation)

				# Check if this collocation already appeared
				if collocation in tokenset_results:
					# If so, just increase the frequency count
					tokenset_results[collocation] += tpl[1]
				else:
					tokenset_results[collocation] = tpl[1]

			# Add to the overall results
			if tokenset_results:

				sorted_results = sorted(tokenset_results.items(), key=operator.itemgetter(1), reverse=True)

				# Save all results or just the most frequent ones.
				# Also allow a smaller amount of results than the max.
				output = max_output
				if len(sorted_results) < max_output or max_output == 0:
					output = len(sorted_results)

				for i in range(output):

					# Write each word to a separate key
					# so they will become separate columns.
					result = {}
					li_collocation = sorted_results[i][0].split(" ")
					for n in range(n_size):
						result["word_" + str(n + 1)] = li_collocation[n]
					result["value"] = sorted_results[i][1]
					result["date"] = date_string

					results.append(result)

				max_output = max_output

		if not results:
			return

		# Generate csv and finish
		self.dataset.update_status("Writing to csv and finishing")
		self.write_csv_items_and_finish(results)

	def get_collocations(self, tokens, window_size, n_size, min_frequency=None, query_string=False, forbidden_words=False):
		""" Generates a tuple of word collocations (bigrams or trigrams).
		:param li, tokens:				list of tokens
		:param int, window_size: 		size of word window (context) to calculate the ngrams from
		:param int, n_size:				n-gram size. 1=unigrams, 2=bigrams, 3=trigrams
		:param int, min_frequency:			Frequency filter - only return collocations more than this value.
		:param str, query_string:		if given, only return collocations with this word.
										If emtpy, generates collocations for the overall corpus.
		:param str, forbidden_words:	possible list of words to exclude from the results

		:return: list of tuples with collocations 
		
		"""
		
		# Two-word collocations (~ bigrams)
		if n_size == 2:
			finder = BigramCollocationFinder.from_words(tokens, window_size=window_size)

			# Filter out combinations not containing the query string
			if query_string:
				word_filter = lambda w1, w2: not any(string in (w1, w2) for string in query_string)
				finder.apply_ngram_filter(word_filter)

				# Filter out two times the occurance of the same query string
				duplicate_filter = lambda w1, w2: (w1 in query_string and w2 in query_string)
				finder.apply_ngram_filter(duplicate_filter)
			
			# Filter out forbidden words
			if forbidden_words:
				forbidden_words_filter = lambda w1, w2: any(string in (w1, w2) for string in forbidden_words)
				finder.apply_ngram_filter(forbidden_words_filter)

		# Three-word collocations (~ trigrams)
		elif n_size == 3:
			finder = TrigramCollocationFinder.from_words(tokens, window_size=window_size)

			# Filter out combinations not containing the query string
			if query_string:
				word_filter = lambda w1, w2, w3: not any(string in (w1, w2, w3) for string in query_string)
				finder.apply_ngram_filter(word_filter)
			
			# Filter out forbidden words
			if forbidden_words:
				forbidden_words_filter = word_filter = lambda w1, w2, w3: any(string in (w1, w2, w3) for string in forbidden_words)
				finder.apply_ngram_filter(word_filter)

		else:
			return "n_size is not valid. Use 1 or 2"

		# Filter out words appearing less than this
		if min_frequency and min_frequency > 1:
			finder.apply_freq_filter(min_frequency)

		colocations = sorted(finder.ngram_fd.items(), key=operator.itemgetter(1), reverse=True)
		return colocations