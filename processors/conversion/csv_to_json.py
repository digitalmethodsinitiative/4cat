"""
Convert a CSV file to JSON
"""
import json

from backend.lib.processor import BasicProcessor
from common.lib.compatibility import Compatibility

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

class ConvertCSVToJSON(BasicProcessor):
	"""
	Convert a CSV file to JSON
	"""
	type = "convert-csv"  # job type ID
	category = "Conversion"  # category
	title = "Convert to JSON"  # title displayed in UI
	description = "Change a CSV file to a JSON file"  # description displayed in UI
	extension = "json"  # extension of result file, used internally and in UI
	icon = "square-js"

	# Allow on CSV datasets
	compatibility = Compatibility(extensions={"csv"})

	def process(self):
		"""
		This takes a CSV file as input and writes the same data as a JSON file
		"""
		posts = 0
		self.dataset.update_status("Converting posts")

		# we write to file per row, instead of json.dumps()ing all of it at
		# once, since else we risk having to keep a lot of data in memory,
		# and this buffers one row at most
		with self.dataset.get_results_path().open("w") as output:
			output.write("[")
			for post in self.source_dataset.iterate_items(self):
				posts += 1

				if posts > 1:
					output.write(",")

				output.write(json.dumps(post))
			output.write("]")

		self.dataset.update_status("Finished.")
		self.dataset.finish(num_rows=posts)
