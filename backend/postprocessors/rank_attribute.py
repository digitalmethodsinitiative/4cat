"""
Generate ranking per post attribute
"""
import datetime
import re

from collections import OrderedDict
from itertools import islice
from csv import DictReader

from backend.abstract.postprocessor import BasicPostProcessor
from backend.lib.helpers import UserInput, convert_to_int


class AttributeRanker(BasicPostProcessor):
	"""
	Count occurrence of values for a given post attribute for a given time
	frame

	For example, this may be used to count the most-used author names per year;
	most-occurring country codes per month; overall top host names, etc
	"""
	type = "attribute-frequencies"  # job type ID
	category = "Post metrics"  # category
	title = "Attribute frequencies"  # title displayed in UI
	description = "Count frequencies for a given post attribute and aggregate the results, sorted by most-occurring value. Optionally results may be counted per period."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	# the following determines the options available to the user via the 4CAT
	# interface.
	options = {
		"attribute": {
			"type": UserInput.OPTION_CHOICE,
			"default": True,
			"options": {
				"author": "Username",
				"image_md5": "Image (hash)",
				"image_file": "Image (filename)",
				"country_code": "Country code",
				"url": "URLs (in post body)",
				"hostname": "Host names (in post body)"
			},
			"help": "Attribute to aggregate"
		},
		"timeframe": {
			"type": UserInput.OPTION_CHOICE,
			"default": "all",
			"options": {"all": "Overall", "year": "Year", "month": "Month", "day": "Day"},
			"help": "Count frequencies per"
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

		# we use these to extract URLs and host names if needed
		link_regex = re.compile(r"https?://[^\s]+")
		www_regex = re.compile(r"^www\.")

		# convenience variables
		timeframe = self.parameters.get("timeframe", self.options["timeframe"]["default"])
		attribute = self.parameters.get("attribute", self.options["attribute"]["default"])
		cutoff = convert_to_int(self.parameters.get("top", self.options["top"]["default"]))

		# we need to be able to order the values later, chronologically, so use
		# and OrderedDict; all frequencies go into this variable
		items = OrderedDict()

		self.query.update_status("Reading source file")
		with open(self.source_file, encoding='utf-8') as source:
			csv = DictReader(source)
			for post in csv:
				# determine where to put this data
				if timeframe == "all":
					time_unit = "overall"
				else:
					timestamp = int(datetime.datetime.strptime(post["timestamp"], "%Y-%m-%d %H:%M:%S").timestamp())
					date = datetime.datetime.fromtimestamp(timestamp)
					if timeframe == "year":
						time_unit = str(date.year)
					elif timeframe == "month":
						time_unit = str(date.year) + "-" + str(date.month)
					else:
						time_unit = str(date.year) + "-" + str(date.month) + "-" + str(date.day)

				# again, we need to be able to sort, so OrderedDict it is
				if time_unit not in items:
					items[time_unit] = OrderedDict()

				# get values from post
				if attribute in ("url", "hostname"):
					# URLs need some processing because there may be multiple per post
					post_links = link_regex.findall(post["body"])
					if not post_links:
						values = []

					if attribute == "hostname":
						values = [www_regex.sub("", link.split("/")[2]) for link in post_links]
					else:
						values = list(post_links)
				else:
					# simply copy the CSV column
					values = [post[attribute]]

				# keep track of occurrences of found items per relevant time period
				for value in values:
					if value not in items[time_unit]:
						items[time_unit][value] = 0

					items[time_unit][value] += 1

		# sort by time and frequency
		self.query.update_status("Sorting items")
		sorted_items = OrderedDict((key, items[key]) for key in sorted(items.keys()))
		for time_unit in sorted_items:
			sorted_unit = OrderedDict((item, sorted_items[time_unit][item]) for item in
									  sorted(sorted_items[time_unit], reverse=True,
											 key=lambda key: sorted_items[time_unit][key]))
			sorted_items[time_unit].clear()
			sorted_items[time_unit].update(sorted_unit)

			if cutoff > 0:
				# OrderedDict's API sucks and really needs some extra
				# convenience methods
				sorted_items[time_unit] = OrderedDict(islice(sorted_items[time_unit].items(), cutoff))

		# convert to flat list
		rows = []
		for time_unit in sorted_items:
			for item in sorted_items[time_unit]:
				row = {
					"time": time_unit,
					"item": item,
					"frequency": sorted_items[time_unit][item]
				}

				# we don't need the time column if we're calculating overall
				# values... though maybe for consistency it's better to include
				# it nonetheless?
				if timeframe == "all":
					del row["time"]

				rows.append(row)

		# write as csv
		self.query.write_csv_and_finish(rows)
