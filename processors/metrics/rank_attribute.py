"""
Generate ranking per post attribute
"""
import re

from collections import OrderedDict
from itertools import islice

from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput, convert_to_int, get_interval_descriptor

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

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
				"image_md5": "Image (hash, for 4chan and 8chan datasets)",
				"image_file": "Image (filename, for 4chan and 8chan datasets)",
				"country_name": "Flag country (for 4chan/pol/ datasets)",
				"subreddit": "Subreddit (for Reddit datasets)",
				"search_entity": "Entity (for Telegram datasets)",
				"hashtags": "Hashtag (for datasets with a 'hashtags' column)",
				"mentions": "Mentions (for datasets with a 'mentions' column)"
			},
			"help": "Attribute to aggregate",
			"tooltip": "When choosing 'Regular expression', any value in a post matching the regular expression will be saved as a separate value."
		},
		"timeframe": {
			"type": UserInput.OPTION_CHOICE,
			"default": "all",
			"options": {"all": "Overall", "year": "Year", "month": "Month", "week": "Week", "day": "Day"},
			"help": "Count frequencies per"
		},
		"top": {
			"type": UserInput.OPTION_TEXT,
			"default": 15,
			"help": "Limit to n items"
		},
		"top-style": {
			"type": UserInput.OPTION_CHOICE,
			"default": "per-item",
			"options": {"per-item": "per interval (separate ranking per interval)", "overall": "overall (per-interval ranking for overall top items)"},
			"help": "Determine top items",
			"tooltip": "'Overall' will first determine the most prevalent items across all intervals, then calculate top items per interval using this as a shortlist."
		},
		"filter": {
			"type": UserInput.OPTION_TEXT,
			"default": "",
			"help": "Item filter",
			"tooltip": "Only items matching this will be included in the result. You can use Python regular expressions here."
		},
		"weigh": {
			"type": UserInput.OPTION_TEXT,
			"default": "",
			"help": "Weigh frequencies by column",
			"tooltip": "Frequencies will be multiplied by the value in this column (e.g. 'views'). If the column does not exist or contains a non-numeric value, multiply with 1."
		}
	}

	def process(self):
		"""
		Reads a CSV file, counts occurences of chosen values over all posts,
		and aggregates the results per chosen time frame
		"""

		# convenience variables
		timeframe = self.parameters.get("timeframe")
		attribute = self.parameters.get("attribute")
		rank_style = self.parameters.get("top-style")
		cutoff = convert_to_int(self.parameters.get("top"), 15)
		weighby = self.parameters.get("weigh")

		try:
			if self.parameters.get("filter"):
				filter = re.compile(".*" + self.parameters.get("filter") + ".*")
			else:
				filter = None
		except (TypeError, re.error):
			self.dataset.update_status("Could not complete: regular expression invalid")
			self.dataset.finish(0)
			return

		# This is needed to check for URLs in the "domain" and "url" columns for Reddit submissions
		datasource = self.source_dataset.parameters.get("datasource")

		# we need to be able to order the values later, chronologically, so use
		# and OrderedDict; all frequencies go into this variable
		items = OrderedDict()

		# if we're interested in overall top-ranking items rather than a
		# per-period ranking, we need to do a first pass in which all posts are
		# inspected to determine those overall top-scoring items
		overall_top = {}
		if rank_style == "overall":
			self.dataset.update_status("Determining overall top-%i items" % cutoff)
			for post in self.iterate_items(self.source_file):
				values = self.get_values(post, attribute, filter, weighby)
				for value in values:
					if value not in overall_top:
						overall_top[value] = 0

					overall_top[value] += 1

			overall_top = sorted(overall_top, key=lambda item: overall_top[item], reverse=True)[0:cutoff]

		# now for the real deal
		self.dataset.update_status("Reading source file")
		for post in self.iterate_items(self.source_file):
			# determine where to put this data
			time_unit = get_interval_descriptor(post, timeframe)
			if time_unit not in items:
				items[time_unit] = OrderedDict()

			# get values from post
			values = self.get_values(post, attribute, filter, weighby)

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
					"date": time_unit,
					"item": item,
					"value": sorted_items[time_unit][item]
				}

				rows.append(row)

		# write as csv
		if rows:
			self.write_csv_items_and_finish(rows)
		else:
			self.dataset.update_status("No posts contain the requested attributes.")
			self.dataset.finish(0)

	def get_values(self, post, attribute, filter, weighby=None):
		"""
		Get relevant values for attribute per post

		:param dict post:  Post dictionary
		:param str attribute:  Attribute to extract from post body
		:param filter:  A compiled regular expression to filter values with, or None
		:return list:  Items found for attribute
		"""
		# we use these to extract URLs and host names if needed
		link_regex = re.compile(r"https?://[^\s\]()]+")
		www_regex = re.compile(r"^www\.")

		if attribute in ("url", "hostname"):
			# URLs need some processing because there may be multiple per post
			post_links = link_regex.findall(post["body"])

			if "url" in post and link_regex.match(post["url"]):
				# some datasources may provide a specific URL per post
				# as a separate attribute
				post_links.append(post["url"])

			if "urls" in post and link_regex.match(post["urls"]):
				# some datasources may provide a specific URL per post
				# as a separate attribute
				for url in post["urls"].split(","):
					if url.strip():
						post_links.append(url)

			if attribute == "hostname":
				values = []
				for urlbits in post_links:
					urlbits = urlbits.split("/")
					if len(urlbits) >= 3:
						values.append(www_regex.sub("", urlbits[2]))
			else:
				values = post_links
		elif attribute == "hashtags":
			values = [item for item in post.get("hashtags", "").split(",") if item.strip()]
		elif attribute == "mentions":
			values = [item for item in post.get("mentions", "").split(",") if item.strip()]
		else:
			# simply copy the CSV column
			values = [post.get(attribute, "")]

		if not values:
			return []
		else:
			return [value for value in values if not filter or filter.match(value)]