
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
from backend.lib.exceptions import ProcessorInterruptedException

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

class ExtractNouns(BasicProcessor):  #TEMPORARILY DISABLED
	"""
	Rank vectors over time
	"""
	type = "get-entities"  # job type ID
	category = "Text analysis" # category
	title = "Extract named entities"  # title displayed in UI
	description = "Get the prediction of various named entities from a text, ranked on frequency. Be sure to have selected \"Named Entity Recognition\" in the previous module"  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	accepts = ["linguistic-features"]

	input = "zip"
	output = "csv"

	options = {
		"entities": {
			"type": UserInput.OPTION_MULTI,
			"default": [],
			"options": {
				"PERSON": "PERSON: People, including fictional.",
				"NORP": "NORP: Nationalities or religious or political groups.",
				"FAC": "FAC: Buildings, airports, highways, bridges, etc.",
				"ORG": "ORG: Companies, agencies, institutions, etc.",
				"GPE": "GPE: Countries, cities, states.",
				"LOC": "LOC: Non-GPE locations, mountain ranges, bodies of water.",
				"PRODUCT": "PRODUCT: Objects, vehicles, foods, etc. (Not services.)",
				"EVENT": "EVENT: Named hurricanes, battles, wars, sports events, etc.",
				"WORK_OF_ART": "WORK_OF_ART: Titles of books, songs, etc.",
				"LAW": "LAW: Named documents made into laws.",
				"LANGUAGE": "LANGUAGE: Any named language.",
				"DATE": "DATE: Absolute or relative dates or periods.",
				"TIME": "TIME: Times smaller than a day.",
				"PERCENT": "PERCENT: Percentage, including ”%“.",
				"MONEY": "MONEY: Monetary values, including unit.",
				"QUANTITY": "QUANTITY: Measurements, as of weight or distance.",
				"ORDINAL": "ORDINAL: “first”, “second”, etc.",
				"CARDINAL": "CARDINAL: Numerals that do not fall under another type."
			},
			"help": "What types of entities to extract. The above list is derived from the SpaCy documentation (https://spacy.io/api/annotation#named-entities)."
		}
	}

	def process(self):
		"""
		Opens the SpaCy output and gets ze entities.

		"""
		
		# Validate whether the user enabled the right parameters.
		if "ner" not in self.parent.parameters["enable"]:
			self.dataset.update_status("Enable \"Named entity recognition\" in previous module")
			self.dataset.finish(0)

		else:
			# Extract the SpaCy docs first
			self.dataset.update_status("Unzipping SpaCy docs")
			docs = self.extract_docs()
		
			# Store all the entities in this list		
			li_entities = []

			for doc in docs:
				# stop processing if worker has been asked to stop
				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while processing documents")

				for ent in doc.ents:
					if ent.label_ in self.parameters["entities"]:
						li_entities.append((ent.text, ent.label_)) # Add a tuple

			results = []
			if li_entities:
				# Convert to lower and filter out one-letter words. Join the words with the entities so we can group easily.
				li_entities = [str(tpl[0]).lower() + " |#| " + str(tpl[1]) for tpl in li_entities if len(tpl[0]) > 1]
				# Group and rank
				count_nouns = Counter(li_entities).most_common()
				# Unsplit and list the count.
				results = [{"word": tpl[0].split(" |#| ")[0], "entity": tpl[0].split(" |#| ")[1], "count": tpl[1]} for tpl in count_nouns]

			# done!
			if results:
				self.dataset.update_status("Finished")
				self.write_csv_items_and_finish(results)
			else:
				self.dataset.update_status("Finished, but no entities were extracted.")
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