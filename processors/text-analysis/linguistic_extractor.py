"""
Extract linguistic features from text using SpaCy.

"""
import zipfile
import pickle
import re

import spacy
from spacy.tokens import DocBin
from spacy.tokenizer import Tokenizer
from spacy.util import compile_prefix_regex, compile_suffix_regex

from common.lib.helpers import UserInput
from common.lib.exceptions import ProcessorInterruptedException
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
	category = "Text analysis"  # category
	title = "Linguistic features"  # title displayed in UI
	description = "Annotate your text with a variety of linguistic features, including part-of-speech tagging, depencency parsing, and named entity recognition. Subsequent modules can add identified tags and nouns to the original data file. Uses the SpaCy library and the en_core_web_sm model. Currently only available for datasets with less than 100.000 items."  # description displayed in UI
	extension = "zip"  # extension of result file, used internally and in UI

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
			"help": "What linguistic features to extract. Without any of these selected, it simply saves the SpaCy docs (tokenised sentences) as a serialized file. See references for more information."
		}
	}

	def process(self):
		"""
		Reads text and outputs entities per text body.
		"""

		# prepare staging area
		staging_area = self.dataset.get_staging_area()

		self.dataset.update_status("Preparing data")

		# go through all archived token sets and vectorise them
		results = []

		# Load the spacy goods
		nlp = spacy.load("en_core_web_sm")
		nlp.tokenizer = self.custom_tokenizer(nlp)  # Keep words with a dash in between

		# Disable what has _not_ been selected
		options = ["parser", "tagger", "ner"]
		enable = self.parameters.get("enable", False)

		if not enable:
			self.dataset.update_status("Select at least one of the options.")
			self.dataset.finish(0)
			return

		disable = [option for option in options if option not in enable]

		# Get all ze text first so we can process it in batches
		posts = [post["body"] if post["body"] else "" for post in self.iterate_items(self.source_file)]

		# Process the text in batches
		if len(posts) < 100000:
			self.dataset.update_status("Extracting linguistic features")
		else:
			self.dataset.update_status(
				"Extracting linguistic features is currently only available for datasets with less than 100.000 items.")
			self.dataset.finish(0)
			return

		# Make sure only the needed information is extracted.
		attrs = []
		if "tagger" not in disable:
			attrs.append("POS")
		if "parser" not in disable:
			attrs.append("DEP")
		if "ner":
			attrs.append("ENT_IOB")
			attrs.append("ENT_TYPE")
			attrs.append("ENT_ID")
			attrs.append("ENT_KB_ID")

		# DocBin for quick saving
		doc_bin = DocBin(attrs=attrs)

		# Start the processing!
		try:
			for i, doc in enumerate(nlp.pipe(posts, disable=disable)):
				doc_bin.add(doc)

				# It's quite a heavy process, so make sure it can be interrupted
				if self.interrupted:
					raise ProcessorInterruptedException("Processor interrupted while iterating through CSV file")

				if i % 1000 == 0:
					self.dataset.update_status("Done with post %s out of %s" % (i, len(posts)))
		except MemoryError:
			self.dataset.update_status("Out of memory. The dataset may be too large to process. Try again with a smaller dataset.", is_final=True)
			return

		self.dataset.update_status("Serializing results - this will take a while")

		# Then serialize the NLP docs and the vocab
		doc_bytes = doc_bin.to_bytes()

		# Dump ze data in a temporary folder
		with staging_area.joinpath("spacy_docs.pb").open("wb") as outputfile:
			pickle.dump(doc_bytes, outputfile)

		# create zip of archive and delete temporary files and folder
		self.write_archive_and_finish(staging_area, compression=zipfile.ZIP_LZMA)

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