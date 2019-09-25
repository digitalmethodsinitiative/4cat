import datetime
import json

import config

from csv import DictReader

from backend.abstract.processor import BasicProcessor

class flowChart(BasicProcessor):
	"""
	Creates a visualisation showing the 'flow' of elements
	over time (flowChart). Based on the Raphael.js impact visualisation

	"""

	type = "flochart"  # job type ID
	category = "Visual"  # category
	title = "Flow chart"  # title displayed in UI
	description = "Create a flow chart of elements over time."  # description displayed in UI
	extension = "html"  # extension of result file, used internally and in UI

	accepts = ["vector-ranker", "preset-neologisms", "tfidf", "collocations"]  # query types this post-processor accepts as input

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
		with open(config.PATH_ROOT + "/backend/assets/flowchart.html") as template:
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
		with open(source_file, encoding="utf-8") as source:
			csv = DictReader(source)

			labels = []
			timestamps = []

			for post in csv:

				# Set label names
				if post["text"] not in labels:
					labels.append(post["text"])
					label_key = str(len(result["labels"]))
					result["labels"][label_key] = {}
					result["labels"][label_key]["n"] = post["text"]
				else:
					label_key = labels.index(post["text"])

				# Make a bucket when a new timestamp appears
				if post["date"] == "overall":
					timestamp = "overall"
				else:
					if len(post["date"]) == 4: # years
						time_format = "%Y"
					elif 6 <= len(post["date"]) <= 7: # months (2018-1 or 2018-01)
						time_format = "%Y-%m"
					elif 8 <= len(post["date"]) <= 10: # days (2018-1-1, 2018-01-1, 2018-1-01 or 2018-01-01)
						time_format = "%Y-%m-%d"
					timestamp = int(datetime.datetime.strptime(post["date"], time_format).timestamp())

				# Multiply small floats so they can be converted to ints (necessary for tf-idf scores)
				value = float(post["value"])
				if value % 1 != 0:
					value = value * 100
				value = int(value)

				# Add values to results dict
				if timestamp not in timestamps:
					result["buckets"].append({"d":timestamp, "i": [[label_key, value]]})
					timestamps.append(timestamp)
				else:
					result["buckets"][len(result["buckets"]) - 1]["i"].append([label_key, value])

				# Set max value
				if value > result["max"]:
					result["max"] = value

		return result