"""
Generate ranking per post attribute
"""
import datetime
import re

from collections import OrderedDict
from itertools import islice
from csv import DictReader

from backend.abstract.processor import BasicProcessor
from backend.lib.helpers import UserInput, convert_to_int


class AttributeRanker(BasicProcessor):
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
				"url": "URLs (in post body)",
				"hostname": "Host names (in post body)",
				"wildcard": "Regular expression (match any filtered value in post)",
				"image_md5": "Image (hash, for 4chan and 8chan datasets)",
				"image_file": "Image (filename, for 4chan and 8chan datasets)",
				"country_code": "Country code (for 4chan datasets)",
				"subreddit": "Subreddit (for Reddit datasets)"
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
		},
		"top-style": {
			"type": UserInput.OPTION_CHOICE,
			"default": "per-item",
			"options": {"per-item": "per interval (separate ranking per interval)", "overall": "overall (per-interval ranking for overall top items)"},
			"help": "Determine top items"
		},
		"regex": {
			"type": UserInput.OPTION_TEXT,
			"default": "",
			"help": "Filter for items (Python regular expression)"
		}
	}

	def process(self):
		"""
		Reads a CSV file, counts occurences of chosen values over all posts,
		and aggregates the results per chosen time frame
		"""

		# convenience variables
		timeframe = self.parameters.get("timeframe", self.options["timeframe"]["default"])
		attribute = self.parameters.get("attribute", self.options["attribute"]["default"])
		rank_style = self.parameters.get("top-style", self.options["top-style"]["default"])
		cutoff = convert_to_int(self.parameters.get("top", self.options["top"]["default"]))

		try:
			filter = re.compile(self.parameters.get("regex", None))
		except (TypeError, re.error):
			self.dataset.update_status("Could not complete: regular expression invalid")
			self.dataset.finish(0)
			return

		# This is needed to check for URLs in the "domain" and "url" columns for Reddit submissions
		datasource = self.parent.parameters.get("datasource")

		# we need to be able to order the values later, chronologically, so use
		# and OrderedDict; all frequencies go into this variable
		items = OrderedDict()

		# if we're interested in overall top-ranking items rather than a
		# per-period ranking, we need to do a first pass in which all posts are
		# inspected to determine those overall top-scoring items
		overall_top = {}
		if rank_style == "overall":
			self.dataset.update_status("Determining overall top-%i items" % cutoff)
			with open(self.source_file, encoding='utf-8') as source:
				csv = DictReader(source)
				for post in csv:
					values = self.get_values(post, attribute, filter)
					for value in values:
						if value not in overall_top:
							overall_top[value] = 0

						overall_top[value] += 1

			overall_top = sorted(overall_top, key=lambda item: overall_top[item], reverse=True)[0:cutoff]

		# now for the real deal
		self.dataset.update_status("Reading source file")
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
						time_unit = str(date.year) + "-" + str(date.month).zfill(2)
					else:
						time_unit = str(date.year) + "-" + str(date.month).zfill(2) + "-" + str(date.day).zfill(2)

				# again, we need to be able to sort, so OrderedDict it is
				if time_unit not in items:
					items[time_unit] = OrderedDict()

				# get values from post
				values = self.get_values(post, attribute, filter)

				# keep track of occurrences of found items per relevant time period
				for value in values:
					if rank_style == "overall" and value not in overall_top:
						continue

					if value not in items[time_unit]:
						items[time_unit][value] = 0

					items[time_unit][value] += 1

		# sort by time and frequency
		self.dataset.update_status("Sorting items")
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
		self.dataset.write_csv_and_finish(rows)

	def get_values(self, post, attribute, filter):
		"""
		Get relevant values for attribute per post

		:param dict post:  Post dictionary
		:param str attribute:  Attribute to extract from post body
		:param filter:  A compiled regular expression to filter values with, or None
		:return list:  Items found for attribute
		"""
		# we use these to extract URLs and host names if needed
		link_regex = re.compile(r"https?://[^\s]+")
		www_regex = re.compile(r"^www\.")

		if attribute == "wildcard":
			return filter.findall(post["body"])
		elif attribute in ("url", "hostname"):
			# URLs need some processing because there may be multiple per post
			post_links = link_regex.findall(post["body"])

			if "url" in post:
				# some datasources may provide a specific URL per post
				# as a separate attribute
				post_links.append(post["url"])

			if attribute == "hostname":
				values = [www_regex.sub("", link.split("/")[2]) for link in post_links]
			else:
				values = post_links
		else:
			# simply copy the CSV column
			values = [post.get(attribute, "")]

		return [value for value in values if not filter or filter.match(value)]