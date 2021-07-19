"""
Generate ranking per hateful word
"""
import datetime

from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput, convert_to_int

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters", "hatebase.org"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class HatebaseRanker(BasicProcessor):
	"""
	Count occurrence of values for a given post attribute for a given time
	frame

	For example, this may be used to count the most-used author names per year;
	most-occurring country codes per month; overall top host names, etc
	"""
	type = "hatebase-frequencies"  # job type ID
	category = "Post metrics"  # category
	title = "Top hateful phrases"  # title displayed in UI
	description = "Count frequencies for hateful words and phrases found in the dataset and aggregate the results, sorted by most-occurring value. Optionally results may be counted per period."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor on previous Hatebase analyses

		:param module: Dataset or processor to determine compatibility with
		"""
		return module.type == "hatebase-data"

	# the following determines the options available to the user via the 4CAT
	# interface.
	options = {
		"scope": {
			"type": UserInput.OPTION_CHOICE,
			"default": "all",
			"options": {
				"all": "Ambigous and unambiguous",
				"ambiguous": "Ambiguous terms only",
				"unambiguous": "Unambiguous terms only"
			},
			"help": "Terms to consider"
		},
		"timeframe": {
			"type": UserInput.OPTION_CHOICE,
			"default": "all",
			"options": {"all": "Overall", "year": "Year", "month": "Month", "day": "Day"},
			"help": "Count frequencies per"
		},
		"top-style": {
			"type": UserInput.OPTION_CHOICE,
			"default": "per-item",
			"options": {"per-item": "per interval (separate ranking per interval)",
						"overall": "overall (per-interval ranking for overall top items)"},
			"help": "Determine top items",
			"tooltip": "'Overall' will first determine the most prevalent items across all intervals, then calculate top items per interval using this as a shortlist."
		},
		"top": {
			"type": UserInput.OPTION_TEXT,
			"default": 15,
			"help": "Limit to this amount of top items (0 for unlimited)"
		}
	}

	def process(self):
		"""
		Reads a CSV file, counts occurences of chosen values over all posts,
		and aggregates the results per chosen time frame
		"""

		# convenience variables
		timeframe = self.parameters.get("timeframe")
		scope = self.parameters.get("scope")
		rank_style = self.parameters.get("top-style")
		cutoff = convert_to_int(self.parameters.get("top"), 15)

		# This is needed to check for URLs in the "domain" and "url" columns for Reddit submissions
		datasource = self.source_dataset.parameters.get("datasource")

		# now for the real deal
		self.dataset.update_status("Reading source file")
		overall_top = {}
		interval_top = {}

		for post in self.iterate_items(self.source_file):
			# determine where to put this data
			if timeframe == "all":
				time_unit = "overall"
			else:
				try:
					timestamp = int(datetime.datetime.strptime(post["timestamp"], "%Y-%m-%d %H:%M:%S").timestamp())
				except ValueError:
					timestamp = 0
				date = datetime.datetime.utcfromtimestamp(timestamp)
				if timeframe == "year":
					time_unit = str(date.year)
				elif timeframe == "month":
					time_unit = str(date.year) + "-" + str(date.month).zfill(2)
				else:
					time_unit = str(date.year) + "-" + str(date.month).zfill(2) + "-" + str(date.day).zfill(2)

			if time_unit not in interval_top:
				interval_top[time_unit] = {}

			if scope == "unambiguous":
				terms = post["hatebase_terms_unambiguous"]
			elif scope == "ambiguous":
				terms = post["hatebase_terms_ambiguous"]
			else:
				terms = post["hatebase_terms"]

			terms = terms.split(",")
			if not terms:
				continue

			for term in terms:
				if not term.strip():
					continue

				if term not in overall_top:
					overall_top[term] = 0

				overall_top[term] += 1

				if term not in interval_top[time_unit]:
					interval_top[time_unit][term] = 0

				interval_top[time_unit][term] += 1

		# this eliminates all items from the results that were not in the
		# *overall* top-occuring items. This only has an effect when vectors
		# were generated for multiple intervals
		if rank_style == "overall":
			overall_top = {item: overall_top[item] for item in
						   sorted(overall_top, key=lambda x: overall_top[x], reverse=True)[0:cutoff]}

			filtered_results = {}
			for interval in interval_top:
				filtered_results[interval] = {}
				for term in interval_top[interval]:
					if term in overall_top:
						filtered_results[interval][term] = interval_top[interval][term]

			interval_top = filtered_results

		rows = []
		for interval in interval_top:
			interval_top[interval] = {term: interval_top[interval][term] for term in
									  sorted(interval_top[interval], reverse=True,
											 key=lambda x: interval_top[interval][x])[0:cutoff]}

		for interval in sorted(interval_top):
			for term in interval_top[interval]:
				rows.append({
					"date": interval,
					"item": term,
					"value": interval_top[interval][term]
				})

		# write as csv
		if rows:
			self.write_csv_items_and_finish(rows)
		else:
			self.dataset.finish(0)
