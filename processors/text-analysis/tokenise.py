"""
Tokenize post bodies
"""
import ahocorasick
import string
import jieba
import json
import re
import os

import nltk
from nltk.stem.snowball import SnowballStemmer
from nltk.stem import WordNetLemmatizer
from nltk.tokenize import word_tokenize, TweetTokenizer, sent_tokenize

from common.lib.helpers import UserInput, get_interval_descriptor
from backend.lib.processor import BasicProcessor
from common.config_manager import config

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
	description = "Splits the post body texts in separate words (tokens). This data can then be used for text analysis. " \
				  "The output is a list of lists (each list representing all post tokens or " \
				  "tokens per sentence)."  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI

	references = [
			"[NLTK tokenizer documentation](https://www.nltk.org/api/nltk.tokenize.html)",
			"[Different types of tokenizers in NLTK](https://chendianblog.wordpress.com/2016/11/25/different-types-of-tokenizers-in-nltk/)",
			"[Words in stopwords-iso word list](https://github.com/stopwords-iso/stopwords-iso/blob/master/stopwords-iso.json)",
			"[Words in Google Books word list](https://github.com/hackerb9/gwordlist)",
			"[Words in cracklib word list](https://github.com/cracklib/cracklib/tree/master/words)",
			"[Words in OpenTaal word list](https://github.com/OpenTaal/opentaal-wordlist)"
	]

	@classmethod
	def is_compatible_with(cls, module=None, user=None):
		"""
		Allow CSV and NDJSON datasets
		"""
		return module.get_extension() in ("csv", "ndjson")

	@classmethod
	def get_options(cls, parent_dataset=None, user=None):
		"""
		Get processor options

		This method by default returns the class's "options" attribute, or an
		empty dictionary. It can be redefined by processors that need more
		fine-grained options, e.g. in cases where the availability of options
		is partially determined by the parent dataset's parameters.

		:param DataSet parent_dataset:  An object representing the dataset that
		the processor would be run on
		:param User user:  Flask user the options will be displayed for, in
		case they are requested for display in the 4CAT web interface. This can
		be used to show some options only to privileges users.
		"""
		options = {
			"columns": {
				"type": UserInput.OPTION_MULTI,
				"help": "Column(s) to tokenise",
				"tooltip": "Each enabled column will be treated as a separate item to tokenise. Columns must contain text."
			},
			"docs_per": {
				"type": UserInput.OPTION_CHOICE,
				"default": "all",
				"options": {"all": "Overall", "year": "Year", "month": "Month", "week": "Week", "day": "Day", "thread": "Thread"},
				"help": "Produce documents per"
			},
			"tokenizer_type": {
				"type": UserInput.OPTION_CHOICE,
				"default": "twitter",
				"options": {
					"twitter": "nltk TweetTokenizer",
					"regular": "nltk word_tokenize",
					"jieba-cut": "jieba (for Chinese text; accurate mode)",
					"jieba-cut-all": "jieba (for Chinese text; full mode)",
					"jieba-search": "jieba (for Chinese text; search engine suggestion style)",
				},
				"help": "Tokeniser",
				"tooltip": "TweetTokenizer is recommended for social media content, as it is optimised for informal language."
			},
			"language": {
				"type": UserInput.OPTION_CHOICE,
				"options": {
					**{language: language[0].upper() + language[1:] for language in SnowballStemmer.languages},
					"other": "Other (language-specific options such as stemming, lemmatizing and sentence splitting will "
							 "have no effect)"
				},
				"default": "english",
				"help": "Language"
			},
			"grouping-per": {
				"type": UserInput.OPTION_CHOICE,
				"default": "item",
				"help": "Group tokens per",
				"options": {
					"item": "Item",
					"sentence": "Sentence in item"
				},
				"tooltip": "This is relevant for some processors such as Word2Vec and Tf-idf. If you don't know what to choose, choose 'item'."
			},
			"stem": {
				"type": UserInput.OPTION_TOGGLE,
				"default": False,
				"help": "Stem tokens (with SnowballStemmer)",
				"tooltip": "Stemming removes suffixes from words: 'running' becomes 'runn', 'bicycles' becomes 'bicycl', etc.",
				"requires": "language!=other"
			},
			"lemmatise": {
				"type": UserInput.OPTION_TOGGLE,
				"default": False,
				"help": "Lemmatise tokens (English only)",
				"tooltip": "Lemmatisation replaces variations of a word with its root form: 'running' becomes 'run', 'bicycles' " \
						   " becomes 'bicycle', 'better' becomes 'good'.",
				"requires": "language==english"
			},
			"accept_words": {
				"type": UserInput.OPTION_TEXT,
				"default": "",
				"help": "Always allow these words",
				"tooltip": "These won't be deleted as stop words. Also won't be stemmed or lemmatised. Separate with commas."
			},
			"reject_words": {
				"type": UserInput.OPTION_TEXT,
				"default": "",
				"help": "Always delete these words",
				"tooltip": "These will be deleted from the corpus. Also won't be stemmed or lemmatised. Separate with commas."
			},
			"filter": {
				"type": UserInput.OPTION_MULTI,
				"default": [],
				"options": {
					#"stopwords-terrier-english": "English stopwords (terrier, recommended)",
					"stopwords-iso-english": "English stopwords (stopwords-iso, recommended)",
					"stopwords-iso-dutch": "Dutch stopwords (stopwords-iso)",
					"stopwords-iso-zh": "Chinese stopwords (stopwords-iso)",
					"stopwords-iso-all": "Stopwords for many languages (including Dutch/English, stopwords-iso)",
					#"wordlist-infochimps-english": "English word list (infochimps)",
					"wordlist-googlebooks-english": "English word list (Google One Million Books pre-2008 top unigrams, recommended)",
					"wordlist-cracklib-english": "English word list (cracklib, originally used for password checks. Warning: computationally heavy)",
					"wordlist-opentaal-dutch": "Dutch word list (OpenTaal)",
					#"wordlist-unknown-dutch": "Dutch word list (unknown origin, larger than OpenTaal)"
				},
				"help": "Word lists to exclude",
				"tooltip": "See the references for information per word list. It is highly recommended to exclude stop words. " \
						   "Choosing more word lists increases processing time."
			},
			"only_unique": {
				"type": UserInput.OPTION_TOGGLE,
				"default": False,
				"help": "Only keep unique words per item",
				"tooltip": "Can be useful to filter out spam."
			}
		}

		if parent_dataset and parent_dataset.get_columns():
			columns = parent_dataset.get_columns()
			options["columns"]["type"] = UserInput.OPTION_MULTI
			options["columns"]["inline"] = True
			options["columns"]["options"] = {v: v for v in columns}
			default_options = [default for default in ["body", "text", "subject"] if default in columns]
			if default_options:
				options["columns"]["default"] = default_options.pop(0)

		return options

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
		columns = self.parameters.get("columns")
		if not columns:
			self.dataset.update_status("No columns selected, aborting.", is_final=True)
			self.dataset.update_status(0)
			return

		if type(columns) is not list:
			columns = [columns]

		self.dataset.update_status("Building filtering automaton")

		link_regex = re.compile(r"https?://[^\s]+")
		symbol = re.compile(r"[" + re.escape(string.punctuation) + "’‘“”" + "]")
		numbers = re.compile(r"\b[0-9]+\b")

		# Twitter tokenizer if indicated
		language = self.parameters.get("language", "english")
		if self.parameters.get("tokenizer_type") == "jieba-cut":
			tokenizer = jieba.cut
			tokenizer_args = {"cut_all": False}
		elif self.parameters.get("tokenizer_type") == "jieba-cut-all":
			tokenizer = jieba.cut
			tokenizer_args = {"cut_all": True}
		elif self.parameters.get("tokenizer_type") == "jieba-search":
			tokenizer = jieba.cut_for_search
			tokenizer_args = {}
		else:
			tokenizer = TweetTokenizer(preserve_case=False).tokenize if self.parameters.get("tokenizer_type") == "twitter" else word_tokenize
			tokenizer_args = {} if self.parameters.get("tokenizer_type") == "twitter" else {"language": language}

		# load word filters - words to exclude from tokenisation
		word_filter = set()
		for wordlist in self.parameters.get("filter", []):
			with config.get('PATH_ROOT').joinpath(f"common/assets/wordlists/{wordlist}.txt").open(encoding="utf-8") as input:
				word_filter = set.union(word_filter, input.read().splitlines())

		# Extend or limit the word filter with optionally added words
		# Remove accepted words from filter
		if self.parameters.get("accept_words"):
			accept_words = [str(word).strip() for word in self.parameters["accept_words"].split(",")]
			for accept_word in accept_words:
				if accept_word in word_filter:
					word_filter.remove(accept_word)

		# Add rejected words to filter
		if self.parameters.get("reject_words"):
			reject_words = [str(word).strip().lower() for word in self.parameters["reject_words"].split(",")]
			word_filter.update(reject_words)

		# Use an Aho-Corasick trie to filter tokens - significantly faster
		# than a native Python list or matching by regex
		automaton = ahocorasick.Automaton()
		for word in word_filter:
			if word:
				# the value doesn't matter to us here, we just want to know if
				# the string occurs
				automaton.add_word(word, 1)

		# initialise pre-processors if needed
		stemmer = None
		lemmatizer = None
		if self.parameters.get("language") != "other":
			if self.parameters.get("stem"):
				stemmer = SnowballStemmer(language)

			if self.parameters.get("lemmatise"):
				lemmatizer = WordNetLemmatizer()

		# Only keep unique words?
		only_unique = self.parameters.get("only_unique")

		# prepare staging area
		staging_area = self.dataset.get_staging_area()

		# process posts
		self.dataset.update_status("Processing items")
		docs_per = self.parameters.get("docs_per")
		grouping = "item" if self.parameters.get("grouping-per", "") == "item" else "sentence"

		# this is how we'll keep track of the subsets of tokens
		output_files = {}
		current_output_path = None
		output_file_handle = None

		# dummy function to pass through data (as an alternative to sent_tokenize later)
		def dummy_function(x, *args, **kwargs):
			return [x]

		# if told so, first split the post into separate sentences
		if grouping == "sentence":
			if language not in [lang.split('.')[0] for lang in os.listdir(nltk.data.find('tokenizers/punkt')) if
								'pickle' in lang]:
				self.dataset.update_status(
					f"Language {language} not available for sentence tokenizer; grouping by item/post instead.")
				sentence_method = dummy_function
			else:
				sentence_method = sent_tokenize
		else:
			sentence_method = dummy_function

		# Collect metadata
		metadata = {'parameters':{'columns':columns, 'grouped_by':grouping, 'intervals':set()}}
		multiple_docs_per_post = True if grouping == 'sentence' or len(columns) > 1 else False
		processed = 0
		for post in self.source_dataset.iterate_items(self):
			# determine what output unit this post belongs to
			if docs_per != "thread":
				try:
					document_descriptor = get_interval_descriptor(post, docs_per)
				except ValueError as e:
					self.dataset.update_status("%s, cannot count items per %s" % (str(e), docs_per), is_final=True)
					self.dataset.update_status(0)
					return
			else:
				document_descriptor = post["thread_id"] if post["thread_id"] else "undefined"

			# Prep metadata
			# document_numbers lists the indexes for documents found in filename relating to this post/item
			# It should only have one index if grouped_by is "item", but may have more if grouped_by is "sentence" or multiple columns are provided
			metadata['parameters']['intervals'].add(document_descriptor)
			metadata[post.get('id')] = {
								'interval': document_descriptor,
								'filename': document_descriptor + ".json",
								'document_numbers': [],
								'documents': {}, # Only needed if there are more than one document per post/item
								}

			groupings = []
			for column in columns:
				column_value = post.get(column)
				# Possible to only check ones? Not if column is blank/None for some rows, but not all.
				if column_value is not None and type(column_value) != str:
					self.dataset.update_status("Column %s contains non text values and cannot be tokenized" % column, is_final=True)
					self.dataset.update_status(0)
					return

				value = [v for v in sentence_method(post[column], language) if v is not None]
				if value:
					groupings.extend(value)

			if processed % 500 == 0:
				self.dataset.update_progress(processed / self.source_dataset.num_rows)
			processed += 1

			# tokenise...
			for document in groupings:
				post_tokens = []

				# clean up text and get tokens from it
				body = link_regex.sub("", document)

				# Use differing tokenizers depending on the user input
				tokens = tokenizer(body, **tokenizer_args)

				# stem, lemmatise and save tokens that are not in filter
				for token in tokens:
					token = token.lower()
					token = numbers.sub("", symbol.sub("", token))

					# skip empty and filtered tokens
					if not token or token in automaton:
						continue

					if self.parameters["stem"] and stemmer:
						token = stemmer.stem(token)

					if self.parameters["lemmatise"] and lemmatizer:
						token = lemmatizer.lemmatize(token)

					# append tokens to the post's token list
					post_tokens.append(token)

				# write tokens to file
				# this writes lists of json lists, with the outer list serialised
				# 'manually' and the token lists serialised by the json library
				if post_tokens:

					# Only keep unique words, if desired
					if only_unique:
						post_tokens = list(set(post_tokens))

					output_file = staging_area.joinpath(document_descriptor + ".json")
					output_path = str(output_file)

					if current_output_path != output_path:
						self.dataset.update_status("Processing items (%s)" % document_descriptor)
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
					metadata[post.get('id')]['document_numbers'].append(output_files[output_path])
					if multiple_docs_per_post:
						metadata[post.get('id')]['documents'][output_files[output_path]] = document
					output_files[output_path] += 1

		if output_file_handle:
			output_file_handle.close()

		# close all json lists
		# we do this now because only here do we know all files have been
		# fully written - if posts are out of order, the tokeniser may
		# need to repeatedly switch between various token files
		for output_path in output_files:
			with open(output_path, "a") as file_handle:
				file_handle.write("\n]")

		# Save the metadata in our staging area
		metadata['parameters']['intervals'] = list(metadata['parameters']['intervals'])
		with staging_area.joinpath(".token_metadata.json").open("w", encoding="utf-8") as outfile:
			json.dump(metadata, outfile)

		# create zip of archive and delete temporary files and folder
		self.write_archive_and_finish(staging_area)
