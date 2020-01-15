"""
Over-time trends
"""
import datetime
import json
import re

from csv import DictReader

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
			"options": {"all": "Overall", "year": "Year", "month": "Month", "day": "Day"},
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
			reader = DictReader(input)
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
			csv = DictReader(source)
			for post in csv:
				# determine where to put this data
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

				if time_unit not in hateful:
					hateful[time_unit] = 0

				if time_unit not in views:
					views[time_unit] = 0

				intervals.add(time_unit)

				activity[time_unit] += 1
				try:
					views[time_unit] += int(post[engagement_field])
				except ValueError:
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
			self.dataset.write_csv_and_finish(rows)
		else:
			self.dataset.finish(0)
