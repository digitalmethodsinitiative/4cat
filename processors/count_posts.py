"""
Collapse post bodies into one long string
"""
import re
import datetime

from csv import DictReader, writer

from backend.lib.helpers import UserInput
from backend.abstract.processor import BasicProcessor
from collections import OrderedDict

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
			"default": "all",
			"options": {"all": "Overall", "year": "Year", "month": "Month", "day": "Day"},
			"help": "Produce counts per"
		}
	}

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a plain text file
		containing all post bodies as one continuous string, sanitized.
		"""

		# OrderedDict because dates and headers should have order
		posts = OrderedDict()
		posts["date"] = "count" #eventual headers

		timeframe = self.parameters.get("timeframe", self.options["timeframe"]["default"])
		
		self.dataset.update_status("Processing posts")
		with self.dataset.get_results_path().open("w") as results:
			with self.source_file.open(encoding="utf-8") as source:

				csv = DictReader(source)
				
				counter = 0

				for post in csv:

					# Add a count for the respective timeframe
					if timeframe == "all":
						date = "overall"
					else:
						timestamp = int(datetime.datetime.strptime(post["timestamp"], "%Y-%m-%d %H:%M:%S").timestamp())
						date = datetime.datetime.fromtimestamp(timestamp)
						if timeframe == "year":
							date = str(date.year)
						elif timeframe == "month":
							date = str(date.year) + "-" + str(date.month)
						else:
							date = str(date.year) + "-" + str(date.month) + "-" + str(date.day)

					if date not in posts:
						posts[date] = 1
					else:
						posts[date] += 1

					counter += 1

					if counter % 10 == 0:
						self.dataset.update_status("Counted through " + str(counter) + " posts.")

			# Write to csv
			csv_writer = writer(results)
			for key, value in posts.items():
				csv_writer.writerow([key, value])

		self.dataset.finish(len(posts))