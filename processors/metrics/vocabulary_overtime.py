"""
Over-time trends
"""
import re

from pathlib import Path

from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput, get_interval_descriptor

import config

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class OvertimeAnalysis(BasicProcessor):
	"""
	Show overall activity levels for Telegram datasets
	"""
	type = "overtime-vocabulary"  # job type ID
	category = "Post metrics"  # category
	title = "Over-time vocabulary prevalence"  # title displayed in UI
	description = "Determines the presence over time of a particular vocabulary in the dataset. Counts how many posts match at least one word in the provided vocabularies."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	references = [
		"[\"Salvaging the Internet Hate Machine: Using the discourse of radical online subcultures to identify emergent extreme speech\" - Unblished paper detailing the OILab extreme speech lexigon](https://oilab.eu/texts/4CAT_Hate_Speech_WebSci_paper.pdf)",
		]

	# the following determines the options available to the user via the 4CAT
	# interface.
	options = {
		"timeframe": {
			"type": UserInput.OPTION_CHOICE,
			"default": "month",
			"options": {"all": "Overall", "year": "Year", "month": "Month", "week": "Week", "day": "Day"},
			"help": "Count frequencies per"
		},
		"partition": {
			"type": UserInput.OPTION_TOGGLE,
			"default": False,
			"help": "Track vocabularies separately",
			"tooltip": "Instead of checking whether a post matches any of the selected vocabularies, provide separate frequencies per vocabulary."
		},
		"vocabulary": {
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
				"oilab-extreme-sexual": "OILab Extreme Speech Lexicon (sexual)",
				"wildcard": "Match everything (useful as comparison, only has effect when tracking separately)"
			},
			"help": "Vocabularies to detect. For explanation, see hatebase.org for the hatebase lexicon and the references of this module for the OILab extreme speech lexicon"
		},
		"vocabulary-custom": {
			"type": UserInput.OPTION_TEXT,
			"default": "",
			"help": "Custom vocabulary (separate with commas)"
		}
	}

	def process(self):
		"""
		Reads a CSV file, counts occurences of chosen values over all posts,
		and aggregates the results per chosen time frame
		"""

		# convenience variables
		timeframe = self.parameters.get("timeframe")
		partition = bool(self.parameters.get("partition"))

		# load vocabularies from word lists
		vocabularies = {}
		for vocabulary_id in self.parameters.get("vocabulary", []):
			vocabulary_file = Path(config.PATH_ROOT, "common/assets/wordlists/%s.txt" % vocabulary_id)
			if not vocabulary_file.exists():
				continue

			if not partition:
				vocabulary_id = "value"

			if vocabulary_id not in vocabularies:
				vocabularies[vocabulary_id] = set()

			with open(vocabulary_file, encoding="utf-8") as vocabulary_handle:
				vocabularies[vocabulary_id] |= set(vocabulary_handle.read().splitlines())

		# add user-defined words
		custom_vocabulary = set([word.strip() for word in self.parameters.get("vocabulary-custom", "").split(",") if word.strip()])
		if custom_vocabulary:
			custom_id = "user-defined" if partition else "value"
			if custom_id not in vocabularies:
				vocabularies[custom_id] = set()

			vocabularies[custom_id] |= custom_vocabulary


		# compile into regex for quick matching
		vocabulary_regexes = {}
		for vocabulary_id in vocabularies:
			if not vocabularies[vocabulary_id]:
				continue
			vocabulary_regexes[vocabulary_id] = re.compile(
				r"\b(" + "|".join([re.escape(term) for term in vocabularies[vocabulary_id] if term]) + r")\b")

		# if the results are partitioned, then it is useful to have a way to
		# compare the frequencies to the overall activity in the graph. This
		# option adds a 'vocabulary' that matches everything, providing that
		# data.
		if partition and "wildcard" in self.parameters.get("vocabulary", []):
			vocabularies["everything"] = set()
			vocabulary_regexes["everything"] = re.compile(r".*")

		# now for the real deal
		self.dataset.update_status("Reading source file")
		activity = {vocabulary_id: {} for vocabulary_id in vocabularies}
		intervals = set()

		processed = 0
		for post in self.iterate_items(self.source_file):
			if not post["body"]:
				post["body"] = ""
				
			if processed % 2500 == 0:
				self.dataset.update_status("Processed %i posts" % processed)
				
			# if 'partition' is false, there will just be one combined
			# vocabulary, but else we'll have different ones we can
			# check separately
			for vocabulary_id in vocabularies:
				if vocabulary_id not in vocabulary_regexes:
					continue

				vocabulary_regex = vocabulary_regexes[vocabulary_id]

				# check if we match
				if not vocabulary_regex.findall(post["body"].lower()):
					continue

				# determine what interval to save the frequency for
				interval = get_interval_descriptor(post, timeframe)
				if interval not in activity[vocabulary_id]:
					activity[vocabulary_id][interval] = 0

				activity[vocabulary_id][interval] += 1
				intervals.add(interval)

			processed += 1

		# turn all that data into a simple three-column frequency table
		rows = []
		for interval in sorted(intervals):
			for vocabulary_id in activity:
				rows.append({
					"date": interval,
					"item": vocabulary_id,
					"value": activity.get(vocabulary_id, {}).get(interval, 0)
				})

		# write as csv
		if rows:
			self.write_csv_items_and_finish(rows)
		else:
			self.dataset.finish(0)
