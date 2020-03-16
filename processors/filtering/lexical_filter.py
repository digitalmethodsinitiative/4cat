"""
Filter posts by lexicon
"""
import shutil
import pickle
import re

from csv import DictReader, DictWriter
from pathlib import Path

from backend.abstract.processor import BasicProcessor
from backend.lib.helpers import UserInput, convert_to_int

import config

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class LexicalFilter(BasicProcessor):
	"""
	Retain only posts matching a given lexicon
	"""
	type = "lexical-filter"  # job type ID
	category = "Filtering"  # category
	title = "Filter by lexicon"  # title displayed in UI
	description = "Copies the dataset, retaining only posts that match any selected lexicon of words or phrases"  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	input = "csv:body"
	output = "csv:body"

	# the following determines the options available to the user via the 4CAT
	# interface.
	options = {
		"replace-parent": {
			"type": UserInput.OPTION_TOGGLE,
			"default": False,
			"help": "Replace original dataset",
			"tooltip": "If this is enabled, the result of this processor will replace the original, parent dataset. This allows you to run other analyses on the filtered data."
		},
		"lexicon": {
			"type": UserInput.OPTION_MULTI,
			"default": [],
			"options": {
				"hatebase-en-unambiguous": "Hatebase.org hate speech list (English, unambiguous terms)",
				"hatebase-en-ambiguous": "Hatebase.org hate speech list (English, ambiguous terms)",
				"hatebase-it-unambiguous": "Hatebase.org hate speech list (Italian, unambiguous terms)",
				"hatebase-it-ambiguous": "Hatebase.org hate speech list (italian, ambiguous terms)",
				"oilab-extreme-other": "OILab Extreme Speech Lexicon (other)",
				"oilab-extreme-anticon": "OILab Extreme Speech Lexicon (anti-conservative)",
				"oilab-extreme-antileft": "OILab Extreme Speech Lexicon (anti-left)",
				"oilab-extreme-antilowerclass": "OILab Extreme Speech Lexicon (anti-lowerclass)",
				"oilab-extreme-antisemitism": "OILab Extreme Speech Lexicon (antisemitic)",
				"oilab-extreme-antidisability": "OILab Extreme Speech Lexicon (anti-disability)",
				"oilab-extreme-homophobia": "OILab Extreme Speech Lexicon (homophobic)",
				"oilab-extreme-islamophobia": "OILab Extreme Speech Lexicon (islamophobic)",
				"oilab-extreme-misogyny": "OILab Extreme Speech Lexicon (misogynistic)",
				"oilab-extreme-racism": "OILab Extreme Speech Lexicon (racist)",
				"oilab-extreme-sexual": "OILab Extreme Speech Lexicon (sexual)"
			},
			"help": "Filter items containing words in these lexicons"
		},
		"lexicon-custom": {
			"type": UserInput.OPTION_TEXT,
			"default": "",
			"help": "Custom lexicon (separate with commas)"
		}
	}

	def process(self):
		"""
		Reads a CSV file, counts occurences of chosen values over all posts,
		and aggregates the results per chosen time frame
		"""

		# replace parent or save as new file?
		replace = bool(self.parameters.get("replace-parent", self.options["replace-parent"]["default"]))

		# load lexicons from word lists
		lexicons = {}
		for lexicon_id in self.parameters.get("lexicon", []):
			lexicon_file = Path(config.PATH_ROOT, "backend/assets/wordlists/%s.pb" % lexicon_id)
			if not lexicon_file.exists():
				continue

			if lexicon_id not in lexicons:
				lexicons[lexicon_id] = set()

			with open(lexicon_file, "rb") as lexicon_handle:
				lexicons[lexicon_id] |= pickle.load(lexicon_handle)

		# add user-defined words
		custom_id = "user-defined"
		if custom_id not in lexicons:
			lexicons[custom_id] = set()

		custom_lexicon = set([word.strip() for word in self.parameters.get("lexicon-custom", "").split(",") if word.strip()])
		lexicons[custom_id] |= custom_lexicon

		# compile into regex for quick matching
		lexicon_regexes = {}
		for lexicon_id in lexicons:
			if not lexicons[lexicon_id]:
				continue
			lexicon_regexes[lexicon_id] = re.compile(
				r"\b(" + "|".join([re.escape(term) for term in lexicons[lexicon_id] if term]) + r")\b", flags=re.IGNORECASE)

		# now for the real deal
		self.dataset.update_status("Reading source file")

		# keep some stats
		processed = 0
		matching_items = 0

		with self.dataset.get_results_path().open("w") as output:
			# get header row, we need to copy it for the output
			with self.source_file.open() as input:
				reader = DictReader(input)
				fieldnames = reader.fieldnames

			# start the output file
			fieldnames.append("matching_lexicons")
			writer = DictWriter(output, fieldnames=fieldnames)
			writer.writeheader()

			# iterate through posts and see if they match
			for post in self.iterate_csv_items(self.source_file):
				if not post.get("body", None):
					continue

				if processed % 2500 == 0:
					self.dataset.update_status("Processed %i posts (%i matching)" % (processed, matching_items))

				# if 'partition' is false, there will just be one combined
				# lexicon, but else we'll have different ones we can
				# check separately
				matching_lexicons = set()
				for lexicon_id in lexicons:
					if lexicon_id not in lexicon_regexes:
						continue

					lexicon_regex = lexicon_regexes[lexicon_id]

					# check if we match
					if not lexicon_regex.findall(post["body"]):
						continue

					matching_lexicons.add(lexicon_id)

				# if none of the lexicons match, the post is not retained
				processed += 1
				if not matching_lexicons:
					continue

				# if one does, record which match, and save it to the output
				post["matching_lexicons"] = ",".join(matching_lexicons)
				writer.writerow(post)

				matching_items += 1

		# file has been written, finish
		if replace:
			parent = self.dataset.get_genealogy()[0]
			shutil.move(self.dataset.get_results_path(), parent.get_results_path())
			self.dataset.update_status("Parent dataset updated.")
			parent.num_rows = matching_items
			self.dataset.finish(-1)
		else:
			self.dataset.finish(matching_items)
