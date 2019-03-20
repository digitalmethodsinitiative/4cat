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
from stop_words import get_stop_words
from nltk.stem.snowball import SnowballStemmer
from nltk.stem.wordnet import WordNetLemmatizer

from backend.lib.helpers import UserInput
from backend.abstract.postprocessor import BasicPostProcessor


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
		"stem": {
			"type": UserInput.OPTION_TOGGLE,
			"default": False,
			"help": "Stem tokens"
		},
		"lemmatise": {
			"type": UserInput.OPTION_TOGGLE,
			"default": False,
			"help": "Lemmatise tokens"
		},
		"timeframe": {
			"type": UserInput.OPTION_CHOICE,
			"default": "all",
			"options": {"all": "Overall", "year": "Year", "month": "Month", "day": "Day"},
			"help": "Produce files per"
		}
	}

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a number of files containing
		tokenised posts, grouped per time unit as specified in the parameters.
		"""
		self.query.update_status("Processing posts")

		link_regex = re.compile(r"https?://[^\s]+")
		token_regex = re.compile(r"[a-zA-Z\-\)\(]{3,50}")

		stopwords = get_stop_words("en")
		stemmer = SnowballStemmer("english")
		lemmatizer = WordNetLemmatizer()

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
			with open(dirname + '/' + subunit + ".pb", "wb") as outputfile:
				pickle.dump(subunits[subunit], outputfile)

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
						output = str(date.year)

				# write each subunit to disk as it is done, to avoid
				# unnecessary RAM hogging
				if current_subunit and current_subunit != output:
					save_subunit(current_subunit)
					self.query.update_status("Processing posts (" + output + ")")
					subunits[current_subunit] = set()

				current_subunit = output

				# deduplication comes for free (well, no extra code) with
				# sets
				if output not in subunits:
					subunits[output] = set()

				# clean up text and get tokens from it
				body = link_regex.sub("", post["body"])
				tokens = token_regex.findall(body)

				# stem, lemmatise and save tokens that are not stopwords
				for token in tokens:
					if token in stopwords:
						continue

					if self.parameters["stem"]:
						token = stemmer.stem(token)

					if self.parameters["lemmatise"]:
						token = lemmatizer.lemmatize(token)

					subunits[output].add(token)

		# save the last subunit we worked on too
		save_subunit(current_subunit)

		# create zip of archive and delete temporary files and folder
		self.query.update_status("Compressing results into archive")
		with zipfile.ZipFile(self.query.get_results_path(), "w") as zip:
			for subunit in subunits:
				zip.write(dirname + '/'+ subunit + ".pb")
				os.unlink(dirname + '/'+ subunit + ".pb")

		# delete temporary files and folder
		shutil.rmtree(dirname)

		# done!
		self.query.update_status("Finished")
		self.query.finish(len(subunits))