"""
Convert a NDJSON file to CSV
"""
import csv
import json

from common.lib.helpers import flatten_dict
from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl", "Stijn Peeters"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)

class ConvertNDJSONtoCSV(BasicProcessor):
	"""
	Convert a NDJSON file to CSV
	"""
	type = "convert-ndjson-csv"  # job type ID
	category = "Conversion"  # category
	title = "Convert NDJSON file to CSV"  # title displayed in UI
	description = "Create a CSV file from an NDJSON file. Note that some data may be lost as CSV files cannot " \
				  "contain nested data."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Determine if processor is compatible with dataset

		:param module: Dataset or processor to determine compatibility with
		"""
		return module.get_extension() == "ndjson"

	def process(self):
		"""
		This takes a NDJSON file as input, flattens the dictionaries, and writes the same data as a CSV file
		"""
		processed = 0
		total_items = self.source_dataset.num_rows
		self.dataset.update_status("Converting file")

		# We first collect all possible columns for the csv file, then
		# for each item make sure there is a value for all the columns (in the
		# second step)
		all_keys = list()
		for item in self.source_dataset.iterate_items(self):
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while writing temporary results to file")

			# Flatten the dict
			# if map_item was used this does (effectively) nothing, if it
			# wasn't this makes sure the values are all scalar
			item = flatten_dict(item)

			# why not use a set() and |? because we want to preserve the key
			# order as much as possible
			for field in item.keys():
				if field not in all_keys:
					all_keys.append(field)

		# Create CSV file
		with self.dataset.get_results_path().open("w", newline="") as output:
			writer = csv.DictWriter(output, fieldnames=all_keys)
			writer.writeheader()

			for item in self.source_dataset.iterate_items(self):
				writer.writerow({key: item.get(key, "") for key in all_keys})
				processed += 1

				if processed % 100 == 0:
					self.dataset.update_status(
						f"Processed {processed}/{total_items} items")
					self.dataset.update_progress(processed / total_items)

		# done!
		self.dataset.update_status("Finished.")
		self.dataset.finish(num_rows=processed)
