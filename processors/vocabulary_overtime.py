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
		"vocabulary": {
			"type": UserInput.OPTION_MULTI,
			"default": [],
			"options": {
				"hatebase-en-unambig": "Hatebase hate speech list (English, unambiguous terms)",
				"hatebase-en-ambig": "Hatebase hate speech list (English, ambiguous terms)",
				"hatebase-it-unambig": "Hatebase hate speech list (Italian, unambiguous terms)",
				"hatebase-it-ambig": "Hatebase hate speech list (italian, ambiguous terms)"
			},
			"help": "Language"
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

		# load vocabularies from word lists
		vocabulary = set()
		for vocabulary_id in self.parameters.get("vocabulary", []):
			vocabulary_file = Path(config.PATH_ROOT, "backend/assets/wordlists/%s.pb" % vocabulary_id)
			if not vocabulary_file.exists():
				continue

			with open(vocabulary_file, "rb") as vocabulary_handle:
				vocabulary |= pickle.load(vocabulary_handle)

		# add user-defined words
		custom_vocabulary = set([word.strip() for word in self.parameters.get("vocabulary-custom", "").split(",")])
		vocabulary |= custom_vocabulary

		# compile into regex for quick matching
		vocabulary_regex = re.compile(r"\b(" + "|".join([re.escape(term) for term in vocabulary if term]) + r")\b")


		# now for the real deal
		self.dataset.update_status("Reading source file")
		activity = {}
		hateful = {}
		views = {}
		intervals = set()

		with self.source_file.open() as input:
			reader = DictReader(input)

			# see if we need to multiply by engagement
			if not self.parameters.get("use-engagement", False):
				engagement_field = None
			elif "views" in reader.fieldnames:
				engagement_field = "views"
			elif "score" in reader.fieldnames:
				engagement_field = "score"
			elif "likes" in reader.fieldnames:
				engagement_field = "likes"
			else:
				engagement_field = None

			# check each post for matches
			for post in reader:
				# this is the check!
				if not vocabulary_regex.findall(post["body"].lower()):
					continue

				# count towards the required interval
				if timeframe == "all":
					time_unit = "overall"
				else:
					try:
						timestamp = int(datetime.datetime.strptime(post["timestamp"], "%Y-%m-%d %H:%M:%S").timestamp())
					except ValueError:
						timestamp = 0
					date = datetime.datetime.fromtimestamp(timestamp)
					if timeframe == "year":
						time_unit = str(date.year)
					elif timeframe == "month":
						time_unit = str(date.year) + "-" + str(date.month).zfill(2)
					else:
						time_unit = str(date.year) + "-" + str(date.month).zfill(2) + "-" + str(date.day).zfill(2)

				if time_unit not in activity:
					activity[time_unit] = 0

				activity[time_unit] += 1

				intervals.add(time_unit)

		rows = []
		for interval in sorted(intervals):
			rows.append({
				"date": interval,
				"item": "matching posts",
				"frequency": activity[interval]
			})

		# write as csv
		if rows:
			self.dataset.write_csv_and_finish(rows)
		else:
			self.dataset.finish(0)
