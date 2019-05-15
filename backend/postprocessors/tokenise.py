"""
Tokenize post bodies
"""
import datetime
import zipfile
import pickle
import re
import os
import shutil

from csv import DictReader
from nltk.stem.snowball import SnowballStemmer
from nltk.stem import WordNetLemmatizer

from backend.lib.helpers import UserInput
from backend.abstract.postprocessor import BasicPostProcessor

import config

class Tokenise(BasicPostProcessor):
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
		"stem": {
			"type": UserInput.OPTION_CHOICE,
			"default": "none",
			"options": {"none": "No stemming", **{language: language[0].upper() + language[1:] for language in SnowballStemmer.languages}},
			"help": "Stem tokens (with SnowballStemmer)"
		},
		"echobrackets": {
			"type": UserInput.OPTION_TOGGLE,
			"default": False,
			"help": "Allow (parentheses) in tokens"
		},
		"lemmatise": {
			"type": UserInput.OPTION_TOGGLE,
			"default": False,
			"help": "Lemmatise tokens (English only)"
		},
		"exclude_duplicates": {
			"type": UserInput.OPTION_TOGGLE,
			"default": False,
			"help": "Exclude duplicate words"
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
		self.query.update_status("Processing posts")

		link_regex = re.compile(r"https?://[^\s]+")
		token_regex = re.compile(r"[a-zA-Z\-]{3,50}")
		token_regex_echobrackets = re.compile(r"[a-zA-Z\-\)\(]{3,50}")

		# load word filters - words to exclude from tokenisation
		word_filter = set()
		for wordlist in self.parameters["filter"]:
			with open(config.PATH_ROOT + "/backend/assets/%s.pb" % wordlist, "rb") as input:
				word_filter = set.union(word_filter, pickle.load(input))

		# initialise pre-processors if needed
		if self.parameters["stem"]:
			stemmer = SnowballStemmer("english")

		if self.parameters["lemmatise"]:
			lemmatizer = WordNetLemmatizer()

		# this is how we'll keep track of the subsets of tokens
		subunits = {}
		current_subunit = ""

		# prepare staging area
		dirname_base = self.query.get_results_path().replace(".", "") + "-tokens"
		dirname = dirname_base
		index = 1
		while os.path.exists(dirname):
			dirname = dirname_base + "-" + str(index)
			index += 1

		os.mkdir(dirname)

		# this needs to go outside the loop because we need to call it one last
		# time after the post loop has finished
		def save_subunit(subunit):
			"""
			Save token set to disk

			:param str subunit:  Subset ID
			"""
			with open(dirname + '/' + subunit + ".pb", "wb") as outputfile:
				pickle.dump(subunits[subunit], outputfile)

		# determine what regex to use for tokens
		if self.query.parameters["echobrackets"]:
			token_regex = token_regex_echobrackets

		# process posts
		self.query.update_status("Processing posts")
		timeframe = self.parameters["timeframe"]
		with open(self.source_file, encoding="utf-8") as source:
			csv = DictReader(source)
			for post in csv:
				# determine what output unit this post belongs to
				if timeframe == "all":
						output = "overall"
				else:
					timestamp = int(datetime.datetime.strptime(post["timestamp"], "%Y-%m-%d %H:%M:%S").timestamp())
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
					self.query.update_status("Processing posts (" + output + ")")
					subunits[current_subunit] = list()  # free up memory

				current_subunit = output

				# create a new list if we're starting a new subunit
				if output not in subunits:
					subunits[output] = list()

				# clean up text and get tokens from it
				body = link_regex.sub("", post["body"])
				tokens = token_regex.findall(body)

				# Only keep unique terms if indicated
				if self.parameters.get("exclude_duplicates", False):
					tokens = set(tokens)

				# stem, lemmatise and save tokens that are not stopwords
				for token in tokens:
					token = token.lower()

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
		self.query.update_status("Compressing results into archive")
		with zipfile.ZipFile(self.query.get_results_path(), "w") as zip:
			for subunit in subunits:
				zip.write(dirname + "/" + subunit + ".pb", subunit + ".pb")
				os.unlink(dirname + "/" + subunit + ".pb")

		# delete temporary files and folder
		shutil.rmtree(dirname)

		# done!
		self.query.update_status("Finished")
		self.query.finish(len(subunits))