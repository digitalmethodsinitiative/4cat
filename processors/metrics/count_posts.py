"""
Collapse post bodies into one long string
"""
import datetime

from common.lib.helpers import UserInput, pad_interval, get_interval_descriptor
from backend.abstract.processor import BasicProcessor

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

class CountPosts(BasicProcessor):
	"""
	Merge post body into one long string
	"""
	type = "count-posts"  # job type ID
	category = "Post metrics" # category
	title = "Count posts"  # title displayed in UI
	description = "Counts how many posts are in the query overall or per timeframe."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	options = {
		"timeframe": {
			"type": UserInput.OPTION_CHOICE,
			"default": "month",
			"options": {"all": "Overall", "year": "Year", "month": "Month", "week": "Week", "day": "Day"},
			"help": "Produce counts per"
		},
		"pad": {
			"type": UserInput.OPTION_TOGGLE,
			"default": True,
			"help": "Make time series continuous - add intervals if no data is available",
			"tooltip": "For example, if there are posts for May and July but not June, June will be included as having 0 posts."
		}
	}


	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a plain text file
		containing all post bodies as one continuous string, sanitized.
		"""

		# OrderedDict because dates and headers should have order
		intervals = {}

		timeframe = self.parameters.get("timeframe")
		add_relative = self.parameters.get("add_relative", False)

		first_interval = "9999"
		last_interval = "0000"

		self.dataset.update_status("Processing posts")
		with self.dataset.get_results_path().open("w") as results:
			counter = 0

			for post in self.iterate_items(self.source_file):
				date = get_interval_descriptor(post, timeframe)

				# Add a count for the respective timeframe
				if date not in intervals:
					intervals[date] = {}
					intervals[date]["absolute"] = 1
				else:
					intervals[date]["absolute"] += 1

				first_interval = min(first_interval, date)
				last_interval = max(last_interval, date)

				counter += 1

				if counter % 2500 == 0:
					self.dataset.update_status("Counted through " + str(counter) + " posts.")

			# pad interval if needed, this is useful if the result is to be
			# visualised as a histogram, for example
			if self.parameters.get("pad") and timeframe != "all":
				missing, intervals = pad_interval(intervals, first_interval, last_interval)

				# Convert 0 values to dict
				for k, v in intervals.items():
					if isinstance(v, int):
						intervals[k] = {"absolute": v}

			# Add relative counts, if needed
			if add_relative:

				self.dataset.update_status("Calculating relative counts.")

				# Set a board, if used for this dataset
				board = self.source_dataset.parameters["board"]
				datasource = self.source_dataset.parameters["datasource"]
				board_sql = "AND board = '" + board + "'" if board else ""

				# Make sure we're using the same right date format.
				if timeframe != "all":
					if timeframe == "year":
						time_format = "YYYY"
					elif timeframe == "month":
						time_format = "YYYY-MM"
					elif timeframe == "week":
						time_format = "YYYY-WW"
					elif timeframe == "day":
						time_format = "YYYY-MM-DD"
					time_sql = "to_char(to_date(date, 'YYYY-MM-DD'), '%s') AS date_str," % time_format
				else:
					time_sql = "'all' AS date_str,"

				# Fetch the total counts per timeframe for this datasource
				total_counts = {row["date_str"]: row["count"] for row in self.db.fetchall(
					"""
					SELECT %s SUM(count) as count FROM metrics
					WHERE datasource = '%s' %s
					GROUP BY date_str
					"""
					% (time_sql, datasource, board_sql))}

				# Quick set to check what dates are in the metrics table
				added_dates = set(total_counts.keys())
				
				# Add the relative counts
				for interval in list(intervals.keys()):

					# Calculate the relative counts if this date is also in teh metrics table. Else set the relative count to None.
					intervals[interval]["relative"] = None
					if interval in added_dates:
						intervals[interval]["relative"] = intervals[interval]["absolute"] / total_counts[interval]

			rows = []
			for interval in intervals:

				row = {
					"date": interval,
					"item": "activity",
					"value": intervals[interval]["absolute"]}

				# Also add relative counts if needed
				if add_relative:
					row["value_relative"] = intervals[interval]["relative"]
				rows.append(row)

		self.write_csv_items_and_finish(rows)

	@classmethod
	def get_options(cls, parent_dataset=None, user=None):
		
		options = cls.options

		# We give an option to add relative trends for local datasources
		if parent_dataset and parent_dataset.parameters.get("datasource") in ("4chan", "8kun", "8chan", "parliaments", "usenet", "breitbart"):
			options["add_relative"] = {
				"type": UserInput.OPTION_TOGGLE,
				"default": False,
				"help": "Add relative counts",
				"tooltip": "Divides the absolute count by the total amount of posts for this timeframe."
			}
		
		return options