"""
Generate ranking per post attribute
"""
import emoji
import re

from collections import OrderedDict
from itertools import islice, chain

from backend.lib.processor import BasicProcessor
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
	title = "Count values"  # title displayed in UI
	description = "Count values in a dataset column, like URLs or hashtags (overall or per timeframe)"  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	references = ["[regex010](https://regex101.com/)"]

	include_missing_data = True

	# the following determines the options available to the user via the 4CAT
	# interface.
	options = {
		"columns": {
			"type": UserInput.OPTION_TEXT,
			"help": "Column(s) to count",
			"default": "body",
			"tooltip": "Items will be counted if one of the selected columns matches the criteria defined below"
		},
		"split-comma": {
			"type": UserInput.OPTION_TOGGLE,
			"help": "Columns can contain multiple comma-sepearated values",
			"tooltip": "When enabled, if a column contains multiple values separated by commas, they will be counted separately",
			"default": True
		},
		"extract": {
			"type": UserInput.OPTION_CHOICE,
			"options": {
				"none": "Use column value",
				"urls": "URLs",
				"hostnames": "Host names",
				"hashtags": "Hashtags (words starting with #)",
				"emoji": "Emoji (each used emoji in the column is counted individually)"
			},
			"help": "Extract from column",
			"tooltip": "This can be used to extract more specific values from the value of the selected column(s); for "
					   "example, to count the hashtags embedded in a post's text"
		},
		"timeframe": {
			"type": UserInput.OPTION_CHOICE,
			"default": "all",
			"options": {"all": "Overall", "year": "Year", "month": "Month", "week": "Week", "day": "Day"},
			"help": "Count values per"
		},
		"top": {
			"type": UserInput.OPTION_TEXT,
			"default": 15,
			"help": "Limit to this amount of results"
		},
		"top-style": {
			"type": UserInput.OPTION_CHOICE,
			"default": "per-item",
			"options": {"per-item": "per timeframe (separate ranking per timeframe)", "overall": "overall (only include overall top items in the timeframe)"},
			"help": "Determine top items",
			"tooltip": "'Overall' will first determine the top values across all timeframes, and then check how often these occur per timeframe."
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
			"tooltip": "Frequencies will be multiplied by the value in this column (e.g. 'views')."
		},
		"to-lowercase": {
			"type": UserInput.OPTION_TOGGLE,
			"default": True,
			"help": "Convert values to lowercase",
			"tooltip": "Merges values with varying cases"
		},
		"count_missing": {
			"type": UserInput.OPTION_TOGGLE,
			"default": True,
			"help": "Include missing data",
			"tooltip": "Blank fields are counted as blank (i.e. \"\") and missing fields as \"missing_data\""
		}
	}

	@classmethod
	def is_compatible_with(cls, module=None, user=None):
		"""
		Allow processor on top image rankings

		:param module: Module to determine compatibility with
		"""
		return module.get_extension() in ["csv", "ndjson"]

	def process(self):
		"""
		Reads a CSV file, counts occurences of chosen values over all posts,
		and aggregates the results per chosen time frame
		"""
		columns = self.parameters.get("columns")
		if type(columns) is not list:
			columns = [columns]

		# convenience variables
		timeframe = self.parameters.get("timeframe")
		split_comma = self.parameters.get("split-comma")
		extract = self.parameters.get("extract")
		rank_style = self.parameters.get("top-style")
		cutoff = convert_to_int(self.parameters.get("top"), 15)
		weighby = self.parameters.get("weigh")
		to_lowercase = self.parameters.get("to-lowercase", True)
		self.include_missing_data = self.parameters.get("count_missing")
		
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

		# this is a placeholder function to map missing values to a placeholder
		def missing_value_placeholder(data, field_name):
			"""
			Check if item is missing
			"""
			return "missing_data"

		# if we're interested in overall top-ranking items rather than a
		# per-period ranking, we need to do a first pass in which all posts are
		# inspected to determine those overall top-scoring items
		overall_top = {}
		if rank_style == "overall":
			if cutoff:
				self.dataset.update_status(f"Determining overall top-{cutoff} items")
			else:
				self.dataset.update_status("Determining overall top items")
			for post in self.source_dataset.iterate_items(self, map_missing=missing_value_placeholder if self.include_missing_data else "default"):
				values = self.get_values(post, columns, filter, split_comma, extract)
				for value in values:
					if to_lowercase:
						value = value.lower()
					if value not in overall_top:
						overall_top[value] = 0

					overall_top[value] += convert_to_int(post.get(weighby, 1), 1)

			overall_top = sorted(overall_top, key=lambda item: overall_top[item], reverse=True)
			if cutoff:
				overall_top = overall_top[:cutoff]

		# now for the real deal
		self.dataset.update_status("Reading source file")
		for post in self.source_dataset.iterate_items(self, map_missing=missing_value_placeholder if self.include_missing_data else "default"):
			# determine where to put this data
			try:
				time_unit = get_interval_descriptor(post, timeframe)
			except ValueError as e:
				self.dataset.update_status("%s, cannot count items per %s" % (str(e), timeframe), is_final=True)
				self.dataset.update_status(0)
				return

			if time_unit not in items:
				items[time_unit] = OrderedDict()

			# get values from post
			values = self.get_values(post, columns, filter, split_comma, extract)

			# keep track of occurrences of found items per relevant time period
			for value in values:
				if to_lowercase:
						value = value.lower()
				
				if rank_style == "overall" and value not in overall_top:
					continue

				if value not in items[time_unit]:
					items[time_unit][value] = 0

				items[time_unit][value] += convert_to_int(post.get(weighby, 1))

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
			self.dataset.update_status("No items contain the requested attributes.")
			self.dataset.finish(0)

	def get_values(self, post, attributes, filter, split_comma, extract):
		"""
		Get relevant values for attribute per post

		:param dict post:  Post dictionary
		:param list attributes:  Attribute to extract from post body
		:param filter:  A compiled regular expression to filter values with, or None
		:param bool split_comma:  Split values by comma?
		:return list:  Items found for attribute
		"""
		# we use these to extract URLs and host names if needed

		values = []
		for attribute in attributes:
			if split_comma:
				item_values = [v.strip() for v in str(post.get(attribute, "")).split(",") if v.strip() or self.include_missing_data]
			else:
				item_values = [post.get(attribute, "")] if post.get(attribute, "") or self.include_missing_data else []

			if extract:
				item_values = list(chain(*[self.extract(v, extract) for v in item_values]))

			if item_values:
				values.extend(item_values)

		if not values:
			return []
		else:
			return set([value for value in values if not filter or filter.match(value)])

	def extract(self, value, look_for):
		"""
		Extract particular types of values from a string

		Sometimes you don't want to count the full string, but only the URLs
		in a string, or the hashtags, etc. This method does that.

		:param str value:  Value to extract values from
		:param str look_for:  What type of value to look for
		:return list:  Found values
		"""
		link_regex = re.compile(r"https?://[^\s\]()]+")
		www_regex = re.compile(r"^www\.")
		values = []

		if look_for in ("urls", "hostnames"):
			links = link_regex.findall(value)

			if look_for == "hostnames":
				for urlbits in links:
					urlbits = urlbits.split("/")
					if len(urlbits) >= 3:
						values.append(www_regex.sub("", urlbits[2]))
			else:
				values += list(links)

			return values

		elif look_for == "hashtags":
			hashtags = list(re.findall(r"#([a-zA-Z0-9_]+)", value))
			return hashtags

		elif look_for == "emoji":
			return [e["emoji"] for e in emoji.emoji_list(value)]

		else:
			return [value]


	@classmethod
	def get_options(cls, parent_dataset=None, user=None):
		"""
		Get processor options

		This method by default returns the class's "options" attribute, or an
		empty dictionary. It can be redefined by processors that need more
		fine-grained options, e.g. in cases where the availability of options
		is partially determined by the parent dataset's parameters.

		:param DataSet parent_dataset:  An object representing the dataset that
		the processor would be run on
		:param User user:  Flask user the options will be displayed for, in
		case they are requested for display in the 4CAT web interface. This can
		be used to show some options only to privileges users.
		"""
		options = cls.options

		if parent_dataset and parent_dataset.get_columns():
			columns = parent_dataset.get_columns()
			options["columns"]["type"] = UserInput.OPTION_MULTI
			options["columns"]["inline"] = True
			options["columns"]["options"] = {v: v for v in columns}
			options["columns"]["default"] = ["body"]

		return options