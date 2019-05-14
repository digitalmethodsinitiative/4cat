import datetime
import json

import config

from csv import DictReader, DictWriter

from backend.lib.helpers import get_absolute_folder, get_lib_url
from backend.abstract.postprocessor import BasicPostProcessor

class rankFlow(BasicPostProcessor):
	"""
	Creates a visualisation showing the 'flow' of elements
	over time (rankFlow). Based on the Raphael.js impact visualisation

	"""

	type = "rankflow"  # job type ID
	category = "Visual"  # category
	title = "RankFlow"  # title displayed in UI
	description = "Create a flow-graph of elements over time."  # description displayed in UI
	extension = "html"  # extension of result file, used internally and in UI

	accepts = ["collocations", "tfidf"]  # query types this post-processor accepts as input

	def process(self):

		# Get json data to use in a graph
		self.query.update_status("Generating graph data")
		data = self.generate_json(self.source_file)
		
		# Return empty when there's no results
		if not data:
			return

		# Get library files
		raphael_js = get_lib_url("raphael.js")
		rankflow_js = get_lib_url("rankflow.js")
		rankflow_css = get_lib_url("rankflow.css")

		# Generate a html file based on the retreived json data
		with open("../assets/rankflow.html") as template:
			output = template.read().replace("**json**", json.dumps(data)).replace("**raphael.js**", raphael_js).replace("**rankflow.js**", rankflow_js).replace("**rankflow.css**", rankflow_css)

		# Write HTML file
		output_file = open(self.query.get_results_path(), "w", encoding="utf-8")
		output_file.write(output)
		output_file.close()

		# Finish
		self.query.update_status("Finished")
		self.query.finish(len(output))

	def generate_json(self, source_file):
		"""
		Generates a JSON structure usable for Raphael.js to make a RankFlow

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
					elif len(post["date"]) == 7: # months
						time_format = "%Y-%m"
					elif len(post["date"]) == 10: # days
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