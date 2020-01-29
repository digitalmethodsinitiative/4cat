
"""
Extract nouns from SpaCy NLP docs.

"""

import zipfile
import csv
import pickle
from collections import Counter
from pathlib import Path

import en_core_web_sm
import spacy
from spacy.tokens import Doc

from backend.lib.helpers import UserInput
from backend.abstract.processor import BasicProcessor

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

class ExtractNouns(BasicProcessor):
	"""
	Rank vectors over time
	"""
	type = "extract-nouns"  # job type ID
	category = "Text analysis" # category
	title = "Extract nouns"  # title displayed in UI
	description = "Get the prediction of nouns from your text corpus, as annotated by SpaCy's part-of-speech tagging. Make sure to have selected \"Part of Speech\" in the previous module, as well as \"Dependency parsing\" if you want to extract compound nouns. The output is a csv with the most-used nouns ranked."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	accepts = ["linguistic-features"]

	input = "zip"
	output = "csv"

	options = {
		"type": {
			"type": UserInput.OPTION_CHOICE,
			"default": ["nouns"],
			"options": {
				"nouns": "Single-word nouns",
				"nouns_and_compounds": "Nouns and compound nouns",
				"noun_chunks": "Noun chunks"
			},
			"help": "Whether to only get 1) separate words indicated as nouns, 2) nouns and compound nouns (nouns with multiple words, e.g.\"United States\") using a custom parser, or 3) noun chunks: nouns plus the words describing them, e.g. \"the old grandpa\". See https://spacy.io/usage/linguistic-features#noun-chunks."
		}
	}

	def process(self):
		"""
		Opens the SpaCy output and gets ze nouns.

		"""

		# Validate whether the user enabled the right parameters.
		# Check part of speech tagging
		if "tagger" not in self.parent.parameters["enable"]:
			self.dataset.update_status("Enable \"Part-of-speech tagging\" in previous module")
			self.dataset.finish(0)

		# Check dependency parsing if nouns and compouns nouns is selected
		elif self.parameters["type"] == "nouns_and_compounds" and "parser" not in self.parent.parameters["enable"]:
			self.dataset.update_status("Enable \"Part-of-speech tagging\" and \"Dependency parsing\" for compound nouns in previous module")
			self.dataset.finish(0)

		# Valid parameters
		else:
			# Extract the SpaCy docs first
			self.dataset.update_status("Unzipping SpaCy docs")
			docs = self.extract_docs()
		
			# Store all the nouns in this list		
			li_nouns = []

			# Simply add each word if its POS is "NOUN"
			if self.parameters["type"] == "nouns":
				for doc in docs:
					li_nouns += [token for token in doc if token.pos_ == "NOUN"]

			# Use SpaCy's noun chunk detection
			elif self.parameters["type"] == "noun_chunks":
				for doc in docs:
					for chunk in doc.noun_chunks:
						li_nouns.append(chunk.text)

			# Use a custom script to get single nouns and compound nouns
			elif self.parameters["type"] == "nouns_and_compounds":

				for doc in docs:
					noun = ""

					for i, token in enumerate(doc):
						
						# Check for common nouns (general, e.g. "people")
						# and proper nouns (specific, e.g. "London")
						if token.pos_ == "NOUN" or token.pos_ == "PROPN":
							# Check if the token is part of a noun chunk
							if token.dep_ == "compound": # Check for a compound relation
								noun = token.text
							else:
								if noun:
									noun += " " + token.text
									li_nouns.append(noun)
									noun = ""
								else:
									li_nouns.append(token.text)
				
			results = []
			if li_nouns:
				# convert to lower and filter out one-letter words
				li_nouns = [str(cap_noun).lower() for cap_noun in li_nouns if len(cap_noun) > 1]

				# Group and rank
				count_nouns = Counter(li_nouns).most_common()
				results = [{"word": tpl[0], "count": tpl[1]} for tpl in count_nouns]

			# done!
			if results:
				self.dataset.update_status("Finished")
				self.write_csv_items_and_finish(results)
			else:
				self.dataset.update_status("Finished, but no nouns were extracted.")
				self.dataset.finish(0)

	def extract_docs(self):
		"""
		Extracts serialised SpaCy docs from a zipped archive.

		:returns: SpaCy docs.

		"""

		with zipfile.ZipFile(str(self.source_file), "r") as archive:
			file_name = archive.namelist()[0] # always just one pickle file

			with archive.open(file_name, "r") as pickle_file:
				doc_bytes, vocab_bytes = pickle.load(pickle_file)
	
			nlp = en_core_web_sm.load()	# Load model

			nlp.vocab.from_bytes(vocab_bytes)
			docs = [Doc(nlp.vocab).from_bytes(b) for b in doc_bytes]

		return docs