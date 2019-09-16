"""
Tokenize post bodies
"""
import datetime
import zipfile
import shutil
import pickle
import re

from csv import DictReader
from nltk.stem.snowball import SnowballStemmer
from nltk.stem import WordNetLemmatizer
from nltk.tokenize import word_tokenize

from backend.lib.helpers import UserInput
from backend.abstract.processor import BasicProcessor

import config

class Tokenise(BasicProcessor):
	"""
	Tokenize posts
	"""
	type = "tokenise-posts"  # job type ID
	category = "Text analysis"  # category
	title = "Tokenise"  # title displayed in UI
	description = "Tokenises post bodies, producing corpus data that may be used for further processing by (for example) corpus analytics software."  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI

	options = {
		"timeframe": {
			"type": UserInput.OPTION_CHOICE,
			"default": "all",
			"options": {"all": "Overall", "year": "Year", "month": "Month", "day": "Day"},
			"help": "Produce files per"
		},
		"language": {
			"type": UserInput.OPTION_CHOICE,
			"options": {language: language[0].upper() + language[1:] for language in SnowballStemmer.languages},
			"default": "english",
			"help": "Language"
		},
		"stem": {
			"type": UserInput.OPTION_TOGGLE,
			"default": False,
			"help": "Stem tokens (with SnowballStemmer)"
		},
		"lemmatise": {
			"type": UserInput.OPTION_TOGGLE,
			"default": False,
			"help": "Lemmatise tokens (English only)"
		},
		"strip_symbols": {
			"type": UserInput.OPTION_TOGGLE,
			"default": False,
			"help": "Strip non-alphanumeric characters (e.g. punctuation)"
		},
		"exclude_duplicates": {
			"type": UserInput.OPTION_TOGGLE,
			"default": False,
			"help": "Remove duplicate words"
		},
		"filter": {
			"type": UserInput.OPTION_MULTI,
			"default": [],
			"options": {
				"stopwords-terrier-english": "English stopwords (terrier, recommended)",
				"stopwords-iso-english": "English stopwords (stopwords-iso)",
				"stopwords-iso-dutch": "Dutch stopwords (stopwords-iso)",
				"stopwords-iso-all": "Multi-language stopwords (stopwords-iso)",
				"wordlist-cracklib-english": "English word list (cracklib, recommended)",
				"wordlist-infochimps-english": "English word list (infochimps)",
				"wordlist-googlebooks-english": "Google Books pre-2012 top unigrams (van Soest)",
				"wordlist-opentaal-dutch": "Dutch word list (OpenTaal)",
				"wordlist-unknown-dutch": "Dutch word list (unknown)"
			},
			"help": "Word lists to exclude (i.e. not tokenise)"
		}
	}

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a number of files containing
		tokenised posts, grouped per time unit as specified in the parameters.
		"""
		self.dataset.update_status("Processing posts")

		link_regex = re.compile(r"https?://[^\s]+")
		symbol = re.compile(r"[^a-zA-Z0-9]")
		numbers = re.compile(r"\b[0-9]+\b")

		# load word filters - words to exclude from tokenisation
		word_filter = set()
		for wordlist in self.parameters["filter"]:
			with open(config.PATH_ROOT + "/backend/assets/wordlists/%s.pb" % wordlist, "rb") as input:
				word_filter = set.union(word_filter, pickle.load(input))

		language = self.parameters.get("language", "english")
		strip_symbols = self.parameters.get("strip_symbols", self.options["strip_symbols"]["default"])

		# initialise pre-processors if needed
		if self.parameters["stem"]:
			stemmer = SnowballStemmer(language)

		if self.parameters["lemmatise"]:
			lemmatizer = WordNetLemmatizer()

		# this is how we'll keep track of the subsets of tokens
		subunits = {}
		current_subunit = ""

		# prepare staging area
		results_path = self.dataset.get_temporary_path()
		results_path.mkdir()

		# this needs to go outside the loop because we need to call it one last
		# time after the post loop has finished
		def save_subunit(subunit):
			"""
			Save token set to disk

			:param str subunit:  Subset ID
			"""
			with results_path.joinpath(subunit + ".pb").open("wb") as outputfile:
				pickle.dump(subunits[subunit], outputfile)

		# process posts
		self.dataset.update_status("Processing posts")
		timeframe = self.parameters["timeframe"]
		with open(self.source_file, encoding="utf-8") as source:
			csv = DictReader(source)
			for post in csv:
				# determine what output unit this post belongs to
				if timeframe == "all":
						output = "overall"
				else:
					if "timestamp_unix" in post:
						timestamp = post["timestamp_unix"]
					else:
						try:
							timestamp = int(datetime.datetime.strptime(post["timestamp"], "%Y-%m-%d %H:%M:%S").timestamp())
						except ValueError:
							timestamp = 0
					date = datetime.datetime.fromtimestamp(timestamp)
					if timeframe == "year":
						output = str(date.year)
					elif timeframe == "month":
						output = str(date.year) + "-" + str(date.month)
					else:
						output = str(date.year) + "-" + str(date.month) + "-" + str(date.day)

				# write each subunit to disk as it is done, to avoid
				# unnecessary RAM hogging
				if current_subunit and current_subunit != output:
					save_subunit(current_subunit)
					self.dataset.update_status("Processing posts (" + output + ")")
					subunits[current_subunit] = list()  # free up memory

				current_subunit = output

				# create a new list if we're starting a new subunit
				if output not in subunits:
					subunits[output] = list()

				# clean up text and get tokens from it
				body = link_regex.sub("", post["body"])
				tokens = word_tokenize(body, language=language)

				# Only keep unique terms if indicated
				if self.parameters.get("exclude_duplicates", False):
					tokens = set(tokens)

				# stem, lemmatise and save tokens that are not stopwords
				for token in tokens:
					token = token.lower()

					if strip_symbols:
						token = numbers.sub("", symbol.sub("", token))

					if token in word_filter:
						continue
					if self.parameters["stem"]:
						token = stemmer.stem(token)

					if self.parameters["lemmatise"]:
						token = lemmatizer.lemmatize(token)

					subunits[output].append(token)

		# save the last subunit we worked on too
		save_subunit(current_subunit)

		# create zip of archive and delete temporary files and folder
		self.dataset.update_status("Compressing results into archive")
		with zipfile.ZipFile(self.dataset.get_results_path(), "w") as zip:
			for subunit in subunits:
				zip.write(results_path.joinpath(subunit + ".pb"), subunit + ".pb")
				results_path.joinpath(subunit + ".pb").unlink()

		# delete temporary files and folder
		shutil.rmtree(results_path)

		# done!
		self.dataset.update_status("Finished")
		self.dataset.finish(len(subunits))