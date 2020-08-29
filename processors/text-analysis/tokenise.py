"""
Tokenize post bodies
"""
import ahocorasick
import datetime
import zipfile
import shutil
import pickle
import json
import re

from pathlib import Path

from nltk.stem.snowball import SnowballStemmer
from nltk.stem import WordNetLemmatizer
from nltk.tokenize import word_tokenize, TweetTokenizer, sent_tokenize

from backend.lib.helpers import UserInput
from backend.abstract.processor import BasicProcessor

import config

__author__ = ["Stijn Peeters", "Sal Hagen"]
__credits__ = ["Stijn Peeters", "Sal Hagen"]
__maintainer__ = ["Stijn Peeters", "Sal Hagen"]
__email__ = "4cat@oilab.eu"

class Tokenise(BasicProcessor):
	"""
	Tokenize posts
	"""
	type = "tokenise-posts"  # job type ID
	category = "Text analysis"  # category
	title = "Tokenise"  # title displayed in UI
	description = "Tokenises post bodies, producing corpus data that may be used for further processing by e.g. NLP. The output is a serialized list of lists, with each post treated as a single document (so no sentence splitting)."  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI

	input = "csv:body"
	output = "zip"

	options = {
		"timeframe": {
			"type": UserInput.OPTION_CHOICE,
			"default": "all",
			"options": {"all": "Overall", "year": "Year", "month": "Month", "week": "Week", "day": "Day"},
			"help": "Produce files per"
		},
		"tokenizer_type": {
			"type": UserInput.OPTION_CHOICE,
			"default": "twitter",
			"options": {"twitter": "nltk TweetTokenizer", "regular": "nltk word_tokenize"},
			"help": "Tokeniser",
			"tooltip": "TweetTokenizer is recommended for social media content, as it is optimised for informal language."
		},
		"language": {
			"type": UserInput.OPTION_CHOICE,
			"options": {language: language[0].upper() + language[1:] for language in SnowballStemmer.languages},
			"default": "english",
			"help": "Language"
		},
		"grouping-per": {
			"type": UserInput.OPTION_CHOICE,
			"default": "post",
			"help": "Group tokens per",
			"options": {
				"post": "Post",
				"sentence": "Sentence in post"
			},
			"tooltip": "This is relevant to some underlying processors such as Word2Vec and Tf-idf. If you don't know what to choose, choose 'post'."
		},
		"stem": {
			"type": UserInput.OPTION_TOGGLE,
			"default": False,
			"help": "Stem tokens (with SnowballStemmer)",
			"tooltip": "Stemming removes suffixes from words: 'running' becomes 'runn', 'bicycles' becomes 'bicycl', and so on."
		},
		"lemmatise": {
			"type": UserInput.OPTION_TOGGLE,
			"default": False,
			"help": "Lemmatise tokens (English only)",
			"tooltip": "Lemmatisation replaces inflections of a word with its root form: 'running' becomes 'run', 'bicycles' becomes 'bicycle', 'better' becomes 'good'."
		},
		"accept_words": {
			"type": UserInput.OPTION_TEXT,
			"default": "",
			"help": "Always allow these words",
			"tooltip": "Separate with commas. These are not stemmed or lemmatised; provide variations yourself if needed."
		},
		"reject_words": {
			"type": UserInput.OPTION_TEXT,
			"default": "",
			"help": "Exclude these words",
			"tooltip": "Separate with commas. These are not stemmed or lemmatised; provide variations yourself if needed."
		},
		"filter": {
			"type": UserInput.OPTION_MULTI,
			"default": [],
			"options": {
				#"stopwords-terrier-english": "English stopwords (terrier, recommended)",
				"stopwords-iso-english": "English stopwords (stopwords-iso, recommended)",
				"stopwords-iso-dutch": "Dutch stopwords (stopwords-iso)",
				"stopwords-iso-all": "Stopwords for many languages (including Dutch/English, stopwords-iso)",
				#"wordlist-infochimps-english": "English word list (infochimps)",
				"wordlist-googlebooks-english": "English word list (Google One Million Books pre-2008 top unigrams, recommended)",
				"wordlist-cracklib-english": "English word list (cracklib, warning: computationally heavy)",
				"wordlist-opentaal-dutch": "Dutch word list (OpenTaal)",
				#"wordlist-unknown-dutch": "Dutch word list (unknown origin, larger than OpenTaal)"
			},
			"help": "Word lists to exclude (i.e. not tokenise). It is highly recommended to exclude stop words. Note that choosing more word lists increases processing time"
		}
	}

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a number of files
		containing tokenised posts, grouped per time unit as specified in the
		parameters.

		Tokens are stored as a JSON dump per 'output unit'; each output unit
		corresponds to e.g. a month or year depending on the processor
		parameters. JSON files are partially encoded 'manually', since we don't
		want to keep all tokens for a given output unit in memory until it's
		done, as for large datasets that may exceed memory capacity. Instead,
		we keep a file handle open while tokenising and write the tokens to
		that file per tokenised post. Since we simply need to store a list of
		strings, we can concatenate these lists manually, only using the json
		export options for the token lists. In other words, files are written
		as such:

		first, the opening bracket for a list of lists:
			[

		then, if not the first token in the list, a comma:
			,

		then for each post, a list of tokens, with json.dumps:
			["token1","token2"]

		then after all tokens are done for an output unit, a closing bracket:
			]

		The result is valid JSON, written in chunks.
		"""
		self.dataset.update_status("Building filtering automaton")

		link_regex = re.compile(r"https?://[^\s]+")
		symbol = re.compile(r"[^a-zA-Z0-9]")
		numbers = re.compile(r"\b[0-9]+\b")

		# Twitter tokenizer if indicated
		if self.parameters.get("tokenizer_type") == "twitter":
			tokenizer = TweetTokenizer(preserve_case=False)
			tweet_tokenizer = True
		else:
			tweet_tokenizer = False

		# load word filters - words to exclude from tokenisation
		word_filter = set()
		for wordlist in self.parameters.get("filter", self.options["filter"]["default"]):
			with open(config.PATH_ROOT + "/backend/assets/wordlists/%s.pb" % wordlist, "rb") as input:
				word_filter = set.union(word_filter, pickle.load(input))

		# Extend or limit the word filter with optionally added words
		# Remove accepted words from filter
		if self.parameters.get("accept_words", self.options["accept_words"]["default"]):
			accept_words = [str(word).strip() for word in self.parameters["accept_words"].split(",")]
			for accept_word in accept_words:
				if accept_word in word_filter:
					word_filter.remove(accept_word)

		# Add rejected words to filter
		if self.parameters.get("reject_words", self.options["reject_words"]["default"]):
			reject_words = [str(word).strip() for word in self.parameters["reject_words"].split(",")]
			word_filter.update(reject_words)

		# Use an Aho-Corasick trie to filter tokens - significantly faster
		# than a native Python list or matching by regex
		automaton = ahocorasick.Automaton()
		for word in word_filter:
			if word:
				# the value doesn't matter to us here, we just want to know if
				# the string occurs
				automaton.add_word(word, 1)

		language = self.parameters.get("language", "english")

		# initialise pre-processors if needed
		if self.parameters.get("stem", self.options["stem"]["default"]):
			stemmer = SnowballStemmer(language)

		if self.parameters.get("lemmatise", self.options["lemmatise"]["default"]):
			lemmatizer = WordNetLemmatizer()

		# prepare staging area
		tmp_path = self.dataset.get_temporary_path()
		tmp_path.mkdir()

		# process posts
		self.dataset.update_status("Processing posts")
		timeframe = self.parameters.get("timeframe", self.options["timeframe"]["default"])
		grouping = "post" if self.parameters.get("grouping-per", "") == "post" else "sentence"

		# this is how we'll keep track of the subsets of tokens
		output_files = {}
		current_output_path = None
		output_file_handle = None

		date_descriptor = "overall"
		for post in self.iterate_csv_items(self.source_file):
			if not post["body"]:
				continue
				
			# determine what output unit this post belongs to
			if timeframe != "all":
				if "timestamp_unix" in post:
					try:
						timestamp = int(post["timestamp_unix"])
					except (ValueError, TypeError) as e:
						timestamp = None
				else:
					try:
						timestamp = int(datetime.datetime.strptime(post["timestamp"], "%Y-%m-%d %H:%M:%S").timestamp())
					except (ValueError, TypeError) as e:
						timestamp = None
				
				if timestamp:

					date = datetime.datetime.utcfromtimestamp(timestamp)

					if timeframe == "year":
						date_descriptor = str(date.year)
					elif timeframe == "month":
						date_descriptor = str(date.year) + "-" + str(date.month)
					elif timeframe == "week":
						date_descriptor = str(date.isocalendar()[0]) + "-" + str(date.isocalendar()[1]).zfill(2)
					else:
						date_descriptor = str(date.year) + "-" + str(date.month) + "-" + str(date.day)
				else:
					# Invalid values can occur e.g. in custom csvs.
					date_descriptor = "invalid_date"

			# if told so, first split the post into separate sentences
			if grouping == "sentence":
				groupings = sent_tokenize(post["body"], language)
			else:
				groupings = [post["body"]]

			# tokenise...
			for document in groupings:
				post_tokens = []

				# clean up text and get tokens from it
				body = link_regex.sub("", document)

				# Use differing tokenizers depending on the user input
				if tweet_tokenizer:
					tokens = tokenizer.tokenize(body)
				else:
					tokens = word_tokenize(body, language=language)

				# stem, lemmatise and save tokens that are not in filter
				for token in tokens:
					token = token.lower()
					token = numbers.sub("", symbol.sub("", token))

					# skip empty and filtered tokens
					if not token or token in automaton:
						continue

					if self.parameters["stem"]:
						token = stemmer.stem(token)

					if self.parameters["lemmatise"]:
						token = lemmatizer.lemmatize(token)

					# append tokens to the post's token list
					post_tokens.append(token)

				# write tokens to file
				# this writes lists of json lists, with the outer list serialised
				# 'manually' and the token lists serialised by the json library
				if post_tokens:
					output_file = tmp_path.joinpath(date_descriptor + ".json")
					output_path = str(output_file)

					if current_output_path != output_path:
						self.dataset.update_status("Processing posts (%s)" % date_descriptor)
						if output_file_handle:
							output_file_handle.close()
						output_file_handle = output_file.open("a")

						if output_path not in output_files:
							output_file_handle.write("[")
							output_files[output_path] = 0

						current_output_path = output_path

					if output_files[current_output_path] > 0:
						output_file_handle.write(",\n")

					output_file_handle.write(json.dumps(post_tokens))
					output_files[output_path] += 1

		if output_file_handle:
			output_file_handle.close()

		# close all json lists
		# we do this now because only here do we know all files have been
		# fully written - if posts are out of order, the tokeniser may
		# need to repeatedly switch between various token files
		for output_path in output_files:
			with open(output_path, "a") as file_handle:
				file_handle.write("]")

		# create zip of archive and delete temporary files and folder
		self.dataset.update_status("Compressing results into archive")
		with zipfile.ZipFile(self.dataset.get_results_path(), "w") as zip:
			for output_path in output_files:
				output_path = Path(output_path)
				zip.write(output_path, output_path.name)
				output_path.unlink()

		# delete temporary folder
		shutil.rmtree(tmp_path)

		# done!
		self.dataset.update_status("Finished")
		self.dataset.finish(len(output_files))