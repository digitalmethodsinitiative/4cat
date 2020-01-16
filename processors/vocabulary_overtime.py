"""
Over-time trends
"""
import datetime
import pickle
import json
import re

from csv import DictReader
from pathlib import Path

from backend.abstract.processor import BasicProcessor
from backend.lib.helpers import UserInput, convert_to_int

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

	input = "csv:body"
	output = "csv:time,item,frequency"

	# the following determines the options available to the user via the 4CAT
	# interface.
	options = {
		"timeframe": {
			"type": UserInput.OPTION_CHOICE,
			"default": "month",
			"options": {"all": "Overall", "year": "Year", "month": "Month", "day": "Day"},
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
				"hatebase-it-ambiguous": "Hatebase.org hate speech list (italian, ambiguous terms)"
			},
			"help": "Vocabularies to detect"
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
		timeframe = self.parameters.get("timeframe", self.options["timeframe"]["default"])
		partition = bool(self.parameters.get("partition", self.options["partition"]["default"]))

		# load vocabularies from word lists
		vocabularies = {}
		for vocabulary_id in self.parameters.get("vocabulary", []):
			vocabulary_file = Path(config.PATH_ROOT, "backend/assets/wordlists/%s.pb" % vocabulary_id)
			if not vocabulary_file.exists():
				continue

			if not partition:
				vocabulary_id = "frequency"

			if vocabulary_id not in vocabularies:
				vocabularies[vocabulary_id] = set()

			with open(vocabulary_file, "rb") as vocabulary_handle:
				vocabularies[vocabulary_id] |= pickle.load(vocabulary_handle)

		# add user-defined words
		custom_id = "user-defined" if partition else "frequency"
		if custom_id not in vocabularies:
			vocabularies[custom_id] = set()

		custom_vocabulary = set([word.strip() for word in self.parameters.get("vocabulary-custom", "").split(",")])
		vocabularies[custom_id] |= custom_vocabulary

		# compile into regex for quick matching
		vocabulary_regexes = {}
		for vocabulary_id in vocabularies:
			vocabulary_regexes[vocabulary_id] = re.compile(r"\b(" + "|".join([re.escape(term) for term in vocabularies[vocabulary_id] if term]) + r")\b")
		print(vocabulary_regexes)

		# now for the real deal
		self.dataset.update_status("Reading source file")
		activity = {vocabulary_id: {} for vocabulary_id in vocabularies}
		intervals = set()

		with self.source_file.open() as input:
			reader = DictReader(input)

			# if 'partition' is false, there will just be one combined
			# vocabulary, but else we'll have different ones we can
			# check separately
			for post in reader:
				for vocabulary_id in vocabularies:
					vocabulary_regex = vocabulary_regexes[vocabulary_id]

					# check if we match
					if not vocabulary_regex.findall(post["body"].lower()):
						continue

					# determine what interval to save the frequency for
					if timeframe == "all":
						interval = "overall"
					else:
						try:
							timestamp = int(datetime.datetime.strptime(post["timestamp"], "%Y-%m-%d %H:%M:%S").timestamp())
						except ValueError:
							timestamp = 0

						date = datetime.datetime.fromtimestamp(timestamp)
						if timeframe == "year":
							interval = str(date.year)
						elif timeframe == "month":
							interval = str(date.year) + "-" + str(date.month).zfill(2)
						else:
							interval = str(date.year) + "-" + str(date.month).zfill(2) + "-" + str(date.day).zfill(2)

					if interval not in activity[vocabulary_id]:
						activity[vocabulary_id][interval] = 0

					activity[vocabulary_id][interval] += 1
					intervals.add(interval)

		# turn all that data into a simple three-column frequency table
		rows = []
		for interval in sorted(intervals):
			for vocabulary_id in vocabularies:
				rows.append({
					"date": interval,
					"item": vocabulary_id,
					"frequency": activity.get(vocabulary_id, {}).get(interval, 0)
				})

		# write as csv
		if rows:
			self.dataset.write_csv_and_finish(rows)
		else:
			self.dataset.finish(0)
