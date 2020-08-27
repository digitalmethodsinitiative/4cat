"""
Over-time trends
"""
import datetime
import json
import csv
import re

from backend.abstract.processor import BasicProcessor
from backend.lib.helpers import UserInput, get_interval_descriptor
from backend.lib.exceptions import ProcessorInterruptedException

import config

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)

class OvertimeAnalysis(BasicProcessor):
	"""
	Show overall activity levels for Telegram datasets
	"""
	type = "overtime-hateful"  # job type ID
	category = "Post metrics"  # category
	title = "Over-time offensivess trend"  # title displayed in UI
	description = "Shows activity, engagement (e.g. views or score) and offensiveness trends over-time. Offensiveness is measured as the amount of words listed on Hatebase that occur in the dataset."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	datasource = ["telegram", "instagram", "reddit"]

	input = "csv:body,author"
	output = "csv:time,item,frequency"

	# the following determines the options available to the user via the 4CAT
	# interface.
	options = {
		"language": {
			"type": UserInput.OPTION_CHOICE,
			"default": "en",
			"options": {
				"en": "English",
				"it": "Italian"
			},
			"help": "Language"
		},
		"timeframe": {
			"type": UserInput.OPTION_CHOICE,
			"default": "all",
			"options": {"all": "Overall", "year": "Year", "month": "Month", "week": "Week", "day": "Day"},
			"help": "Count frequencies per"
		},
		"scope": {
			"type": UserInput.OPTION_CHOICE,
			"default": "all",
			"options": {
				"all": "Ambigous and unambiguous",
				"ambiguous": "Ambiguous terms only",
				"unambiguous": "Unambiguous terms only"
			},
			"help": "Hatebase-listed terms to consider"
		},
		"hatefulness-score": {
			"type": UserInput.OPTION_TEXT,
			"default": 0,
			"help": "Minimum 'offensiveness score' (0-100) for Hatebase terms",
			"min": 0,
			"max": 100
		}
	}

	def process(self):
		"""
		Reads a CSV file, counts occurences of chosen values over all posts,
		and aggregates the results per chosen time frame
		"""

		# convenience variables
		timeframe = self.parameters.get("timeframe", self.options["timeframe"]["default"])
		scope = self.parameters.get("scope", self.options["scope"]["default"])
		min_offensive = self.parameters.get("hatefulness-score", self.options["hatefulness-score"]["default"])

		# determine what vocabulary to use
		language = self.parameters.get("language", "")
		if language not in self.options["language"]["options"]:
			language = self.options["language"]["default"]

		# now for the real deal
		self.dataset.update_status("Reading source file")
		activity = {}
		hateful = {}
		views = {}
		intervals = set()

		with self.source_file.open() as input:
			reader = csv.DictReader(input)
			if "views" in reader.fieldnames:
				engagement_field = "views"
			elif "score" in reader.fieldnames:
				engagement_field = "score"
			elif "likes" in reader.fieldnames:
				engagement_field = "likes"
			else:
				self.dataset.update_status("No engagement metric available for dataset, cannot chart over-time engagement.")
				self.dataset.finish(0)
				return

		with open(config.PATH_ROOT + "/backend/assets/hatebase/hatebase-%s.json" % language) as hatebasedata:
			hatebase = json.loads(hatebasedata.read())

		hatebase = {term.lower(): hatebase[term] for term in hatebase}
		hatebase_regex = re.compile(r"\b(" + "|".join([re.escape(term) for term in hatebase if not min_offensive or (hatebase[term]["average_offensiveness"] and hatebase[term]["average_offensiveness"] > min_offensive)]) + r")\b")

		with open(self.source_file, encoding='utf-8') as source:
			csvfile = csv.DictReader(source)
			for post in csvfile:
				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while reading input")

				time_unit = get_interval_descriptor(post, timeframe)

				# determine where to put this data
				if time_unit not in activity:
					activity[time_unit] = 0

				if time_unit not in hateful:
					hateful[time_unit] = 0

				if time_unit not in views:
					views[time_unit] = 0

				intervals.add(time_unit)

				activity[time_unit] += 1
				try:
					views[time_unit] += int(post[engagement_field])
				except (ValueError, TypeError):
					pass

				terms = []
				for term in hatebase_regex.findall(post["body"].lower()):
					if not term:
						continue
					if "plural_of" in hatebase[term] and hatebase[term]["plural_of"]:
						if hatebase[term]["plural_of"] in terms:
							continue
						elif hatebase[term]["plural_of"] in hatebase:
							term = hatebase[term]["plural_of"]

						if scope == "ambiguous" and not hatebase[term]["is_unambiguous"]:
							terms.append(term)
						elif scope == "unambiguous" and hatebase[term]["is_unambiguous"]:
							terms.append(term)
						elif scope == "all":
							terms.append(term)

				hateful[time_unit] += len(terms)

		rows = []
		for interval in sorted(intervals):
			rows.append({
				"date": interval,
				"item": "offensive language",
				"frequency": hateful[interval]
			})
			rows.append({
				"date": interval,
				"item": "messages",
				"frequency": activity[interval]
			})
			rows.append({
				"date": interval,
				"item": engagement_field,
				"frequency": views[interval]
			})

		# write as csv
		if rows:
			self.write_csv_items_and_finish(rows)
		else:
			self.dataset.finish(0)
