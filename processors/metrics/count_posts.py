"""
Collapse post bodies into one long string
"""
import csv

from common.lib.helpers import UserInput, pad_interval, get_interval_descriptor
from backend.abstract.processor import BasicProcessor

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)

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

		first_interval = "9999"
		last_interval = "0000"

		self.dataset.update_status("Processing posts")
		with self.dataset.get_results_path().open("w") as results:
			counter = 0

			for post in self.iterate_items(self.source_file):
				date = get_interval_descriptor(post, timeframe)

				# Add a count for the respective timeframe
				if date not in intervals:
					intervals[date] = 1
				else:
					intervals[date] += 1

				first_interval = min(first_interval, date)
				last_interval = max(last_interval, date)

				counter += 1

				if counter % 2500 == 0:
					self.dataset.update_status("Counted through " + str(counter) + " posts.")

			# pad interval if needed, this is useful if the result is to be
			# visualised as a histogram, for example
			if self.parameters.get("pad") and timeframe != "all":
				missing, intervals = pad_interval(intervals, first_interval, last_interval)

			# Write to csv
			csv_writer = csv.DictWriter(results, fieldnames=("date", "item", "value"))
			csv_writer.writeheader()
			for interval in intervals:
				csv_writer.writerow({
					"date": interval,
					"item": "activity",
					"value": intervals[interval]})

		self.dataset.finish(len(intervals))