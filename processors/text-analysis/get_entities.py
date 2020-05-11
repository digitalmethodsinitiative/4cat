
"""
Extract nouns from SpaCy NLP docs.

"""

import zipfile
import csv
import pickle
import shutil
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
	description = "Get the prediction of various named entities from a text, ranked on frequency. Be sure to have selected \"Named Entity Recognition\" in the previous module. Currently only available for datasets with less than 25.000 items."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	accepts = ["linguistic-features"]

	input = "zip"
	output = "csv"

	options = {
		"overwrite": {
			"type": UserInput.OPTION_TOGGLE,
			"default": False,
			"help": "Overwrite the source file with extracted features",
			"tooltip": "Will add the column \"entities\" to the source file with the found values per post."
		},
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
			"help": "What types of entities to extract (select at least one)",
			"tooltip": "The above list is derived from the SpaCy documentation (see references)."
		}
	}

	references = [
		"[SpaCy named entities list](https://spacy.io/api/annotation#named-entities)"
	]


	def process(self):
		"""
		Opens the SpaCy output and gets ze entities.

		"""
		
		# Validate whether the user enabled the right parameters.
		if "ner" not in self.parent.parameters["enable"]:
			self.dataset.update_status("Enable \"Named entity recognition\" in previous module")
			self.dataset.finish(0)
			return

		if self.dataset.get_genealogy()[0].num_rows > 25000:
			self.dataset.update_status("Named entity recognition is only available for datasets smaller than 25.000 items.")
			self.dataset.finish(0)
			return

		else:
			# Extract the SpaCy docs first
			self.dataset.update_status("Unzipping SpaCy docs")
			docs = self.extract_docs()
		
			# Store all the entities in this list		
			li_entities = []

			for doc in docs:
				post_entities = []

				# stop processing if worker has been asked to stop
				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while processing documents")

				for ent in doc.ents:
					if ent.label_ in self.parameters["entities"]:
						post_entities.append((ent.text, ent.label_)) # Add a tuple

				li_entities.append(post_entities)

			results = []

			if li_entities:

				# Also add the data to the original csv file, if indicated.
				if self.parameters.get("overwrite"):
					self.update_parent(li_entities)


				all_entities = []
				# Convert to lower and filter out one-letter words. Join the words with the entities so we can group easily.
				for post_ents in li_entities:
					for pair in post_ents:
						if pair and len(pair[0]) > 1:
							pair = pair[0].lower() + " |#| " + pair[1]
							all_entities.append(pair)

				# Group and rank
				count_nouns = Counter(all_entities).most_common()
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

	def update_parent(self, li_entities):
		"""
		Update the original dataset with an "entities" column

		"""

		self.dataset.update_status("Adding entities the source file")

		# Get the parent data path
		parent = self.dataset.genealogy[0]
		parent_path = parent.get_results_path()

		# Get a temporary path where we can store the data
		tmp_path = self.dataset.get_temporary_path()
		tmp_path.mkdir()
		tmp_file_path = tmp_path.joinpath(parent_path.name)

		count = 0

		# Get field names
		with parent_path.open(encoding="utf-8") as input:
			reader = csv.DictReader(input)
			fieldnames = reader.fieldnames
			if "entities" not in fieldnames:
				fieldnames.append("entities")

		# Iterate through the original dataset and add values to a new "entities" column
		self.dataset.update_status("Writing csv with entities.")
		with tmp_file_path.open("w", encoding="utf-8", newline="") as output:

			writer = csv.DictWriter(output, fieldnames=fieldnames)
			writer.writeheader()

			for post in self.iterate_csv_items(parent_path):

				# Format like "Apple ORG, Gates PERSON, ..." and add to the row
				pos_tags = ", ".join([":".join(post_entities) for post_entities in li_entities[count]])
				post["entities"] = pos_tags
				writer.writerow(post)
				count += 1

		# Replace the source file path with the new file
		shutil.copy(str(tmp_file_path), str(parent_path))

		# delete temporary files and folder
		shutil.rmtree(tmp_path)

		self.dataset.update_status("Parent dataset updated.")