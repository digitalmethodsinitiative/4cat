"""
Extract linguistic features from text using SpaCy.

"""
import zipfile
import pickle
import shutil
import csv
import re

import spacy
import en_core_web_sm
from spacy.tokenizer import Tokenizer
from spacy.util import compile_prefix_regex, compile_infix_regex, compile_suffix_regex

from backend.lib.helpers import UserInput
from backend.abstract.processor import BasicProcessor

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen", "Stijn Peeters"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

class LinguisticFeatures(BasicProcessor):
	"""
	Rank vectors over time
	"""
	type = "linguistic-features"  # job type ID
	category = "Text analysis" # category
	title = "Linguistic features"  # title displayed in UI
	description = "Annotate your text with a variety of linguistic features, including part-of-speech tagging, depencency parsing, and named entity recognition. Uses the SpaCy library and the en_core_web_sm model. Currently only available for datasets with less than 25.000 items."  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI

	input = "csv"
	output = "zip"

	references = [
		"[SpaCy Linguistic Features - Documentation](https://spacy.io/usage/linguistic-features/)"
	]
	
	options = {
		"enable": {
			"type": UserInput.OPTION_MULTI,
			"default": [],
			"options": {
				"tagger": "Part-of-speech tagging: Tags the kind of words in a sentence, like nouns and verbs",
				"parser": "Dependency parsing: Extract how words in a sentence relate to each other",
				"ner": "Named entity recognition: Labels what kind of objects appear in a sentence (e.g. Apple -> Organisation)"
			},
			"help": "What linguistic features to extract. Without any of these selected, it simply saves the SpaCy docs (tokenised sentences) as a serialized file. See https://spacy.io/usage/linguistic-features"
		}
	}


	def process(self):
		"""
		Reads text and outputs entities per text body.
		"""

		# prepare staging area
		results_path = self.dataset.get_temporary_path()
		results_path.mkdir()

		self.dataset.update_status("Preparing data")
		
		# go through all archived token sets and vectorise them
		results = []

		# Load the spacy goods
		nlp = spacy.load("en_core_web_sm")
		nlp.tokenizer = self.custom_tokenizer(nlp) # Keep words with a dash in between

		# Disable what has _not_ been selected
		options = ["parser","tagger","ner"]
		enable = self.parameters.get("enable", False)

		if not enable:
			self.dataset.update_status("Select at least one of the options.")
			self.dataset.finish(0)
			return

		disable = [option for option in options if option not in enable]

		with open(self.source_file, encoding="utf-8") as source:

			# Get all ze text first so we can process it in batches
			csv_reader = csv.DictReader(source)
			posts = [post["body"] for post in csv_reader if post["body"]]
			
			# Process the text in batches
			if len(posts) < 25000:
				self.dataset.update_status("Extracting linguistic features")
			else:
				self.dataset.update_status("Extracting linguistic features is currently only available for datasets with less than 25.000 items.")
				self.dataset.finish(0)
				return

			# Start the processing!
			docs = nlp.pipe(posts, disable=disable)

			# Then serialize the NLP docs and the vocab
			self.dataset.update_status("Serializing results - this will take a while")
			doc_bytes = [doc.to_bytes() for doc in docs]
			vocab_bytes = nlp.vocab.to_bytes()

		# Dump ze data in a temporary folder
		with results_path.joinpath("spacy_docs.pb").open("wb") as outputfile:
			pickle.dump((doc_bytes, vocab_bytes), outputfile)

		# create zip of archive and delete temporary files and folder
		self.dataset.update_status("Compressing results into archive")
		with zipfile.ZipFile(self.dataset.get_results_path(), "w") as zip:
			zip.write(results_path.joinpath("spacy_docs.pb"), "spacy_docs.pb")
			results_path.joinpath("spacy_docs.pb").unlink() # Deletes the temporary file
			
		# delete temporary files and folder
		shutil.rmtree(results_path)

		# done!
		self.dataset.update_status("Finished")
		self.dataset.finish(1)

	def custom_tokenizer(self, nlp):
		"""
		Custom tokeniser that does not split on dashes.
		Useful for names (e.g. Hennis-Plasschaert).
		"""
		infix_re = re.compile(r'''[.\,\?\:\;\...\‘\’\`\“\”\"\'~]''')
		prefix_re = compile_prefix_regex(nlp.Defaults.prefixes)
		suffix_re = compile_suffix_regex(nlp.Defaults.suffixes)

		return Tokenizer(nlp.vocab, prefix_search=prefix_re.search,
									suffix_search=suffix_re.search,
									infix_finditer=infix_re.finditer,
									token_match=None)