import datetime
import json
import csv

import config

from backend.abstract.processor import BasicProcessor

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "sal@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)

class FlowChart(BasicProcessor):
	"""
	Creates a visualisation showing the 'flow' of elements
	over time (flowChart). Based on the Raphael.js impact visualisation

	"""

	type = "flochart"  # job type ID
	category = "Visual"  # category
	title = "Interactive Flowchart"  # title displayed in UI
	description = "Create a flow chart of elements over time."  # description displayed in UI
	extension = "html"  # extension of result file, used internally and in UI

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor on rankable items

		:param DataSet module:  Dataset or processor to determine compatibility with
		"""

		return module.is_rankable()
		
	def process(self):

		# Get json data to use in a graph
		self.dataset.update_status("Generating graph data")
		data = self.generate_json(self.source_file)
		
		# Return empty when there's no results
		if not data:
			return

		# We need to use absolute URLs in the generated HTML, because they
		# may be downloaded (ideally they'd be fully self-contained, but that
		# would lead to very big files). So determine what URL we can use to
		# link to 4CAT's server in the generated HTML.
		if config.FlaskConfig.SERVER_HTTPS:
			server_url = "https://" + config.FlaskConfig.SERVER_NAME
		else:
			server_url = "http://" + config.FlaskConfig.SERVER_NAME

		# Generate a html file based on the retreived json data
		with open(config.PATH_ROOT + "/common/assets/flowchart.html") as template:
			output = template.read().replace("**json**", json.dumps(data)).replace("**server**", server_url)

		# Write HTML file
		with self.dataset.get_results_path().open("w", encoding="utf-8") as output_file:
			output_file.write(output)

		# Finish
		self.dataset.update_status("Finished")
		self.dataset.finish(len(output))

	def generate_json(self, source_file):
		"""
		Generates a JSON structure usable for Raphael.js to make a flow chart

		"""

		result = {"max": 0, "buckets":[], "labels": {}}
		
		# Open and loop through the source file
		labels = []
		timestamps = []

		# Make sure we know what time format we're dealing with.
		time_format = False
		guess_time_format = False
		if "timeframe" in self.source_dataset.parameters:
			time_format = self.source_dataset.parameters["timeframe"]

		if not time_format:
			guess_time_format = True
		elif time_format.startswith("year"):
			time_format = "%Y"
		elif time_format.startswith("month"):
			time_format = "%Y-%m"
		elif time_format.startswith("week"):
			time_format = "%Y-%U"
		elif time_format.startswith("day"):
			time_format = "%Y-%m-%d"
		else:
			guess_time_format = True

		for post in self.iterate_items(self.source_file):
			
			# Set label names
			if "item" in post:
				label = post["item"]

			# Different labels for collocations
			elif "word_1" in post:
				# Trigrams
				if "word_3" in post:
					label = post["word_1"] + " " + post["word_2"] + " " + post["word_3"]
				# Bigrams
				else:
					label = post["word_1"] + " " + post["word_2"]

			if label not in labels:
				labels.append(label)
				label_key = str(len(result["labels"]))
				result["labels"][label_key] = {
					"n": label
				}
			else:
				label_key = labels.index(label)

			# If the source_dataset dataset has no valid date parameter,
			# we're going to guess what time format we're dealing with.
			if guess_time_format:
				if len(post["date"]) == 4:  # years
					time_format = "%Y"
				elif 6 <= len(post["date"]) <= 7:  # Assume months (2018-1 or 2018-01)
					time_format = "%Y-%m"
				elif 8 <= len(post["date"]) <= 10:  # days (2018-1-1, 2018-01-1, 2018-1-01 or 2018-01-01)
					time_format = "%Y-%m-%d"

			# Make a bucket when a new timestamp appears
			if post["date"] in ("all", "overall"):
				timestamp = "overall"
			else:
				try:
					timestamp = int(datetime.datetime.strptime(post["date"], time_format).timestamp())
				except ValueError:
					self.dataset.update_status("Encountered invalid date value '%s' in dataset, cannot process" % str(post["date"]), is_final=True)
					return None

			# Multiply small floats so they can be converted to ints (necessary for tf-idf scores)
			value = float(post.get("value"))
			if value % 1 != 0:
				value = value * 100
			value = int(value)

			# Add values to results dict
			if timestamp not in timestamps:
				result["buckets"].append({"d": timestamp, "i": [[label_key, value]]})
				timestamps.append(timestamp)
			else:
				result["buckets"][len(result["buckets"]) - 1]["i"].append([label_key, value])

			# Set max value
			if value > result["max"]:
				result["max"] = value

		return result