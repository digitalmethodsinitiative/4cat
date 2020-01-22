
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
			"help": "Whether to only get 1) separate words indicated as nouns, 2) nouns and compound nouns (nouns with multiple words, e.g.\"United States\") using a custom parser, or 3) noun chunks: nouns plus the words describing them, e.g. \"the old grandpa\" - see https://spacy.io/usage/linguistic-features#noun-chunks."
		},
		"sent_must_contain": {
			"type": UserInput.OPTION_TEXT,
			"default": "",
			"help": "Only extract nouns from sentences that contain these text string(s) (comma-separated, case-insensitive)"
		}
	}

	def process(self):
		"""
		Opens the SpaCy output and gets ze nouns.

		"""

		# Extract the SpaCy docs first
		self.dataset.update_status("Unzipping SpaCy docs")
		docs = self.extract_docs()

		# Extract words that must appear in a sentence
		sent_must_contain = []
		if self.parameters["sent_must_contain"]:
			sent_must_contain = [str(word).strip().lower() for word in self.parameters["sent_must_contain"].split(",")]

		# Store all the nouns in this list		
		li_nouns = []

		for doc in docs:

			# Filter out irrelevant sentences, if needed
			for sent in doc.sents:

				# Stop if sentence does not contain the right string.
				if self.parameters["sent_must_contain"]:
					if not any(must_contain in sent.text.lower() for must_contain in sent_must_contain):
						continue

				# Simply add each word if its POS is "NOUN"
					if self.parameters["type"] == "nouns":	
							li_nouns += [token for token in sent if token.pos_ == "NOUN"]

				# Use SpaCy's noun chunk detection
				elif self.parameters["type"] == "noun_chunks":
					for chunk in sent.noun_chunks:
						li_nouns.append(chunk.text)

				# Use a custom script to get single nouns and compound nouns
				elif self.parameters["type"] == "nouns_and_compounds":
					noun = ""

					for token in sent:
						
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
		self.dataset.update_status("Finished")
		if not results:
			self.dataset.finish(len(results))
		
		self.dataset.write_csv_and_finish(results)

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