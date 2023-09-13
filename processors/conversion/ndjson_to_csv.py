"""
Convert a NDJSON file to CSV
"""
import csv
import json

from common.lib.helpers import flatten_dict
from backend.lib.processor import BasicProcessor
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
	def is_compatible_with(cls, module=None, user=None):
		"""
		Determine if processor is compatible with dataset

		:param module: Module to determine compatibility with
		"""
		return module.get_extension() == "ndjson"

	def process(self):
		"""
		This takes a NDJSON file as input, flattens the dictionaries, and writes the same data as a CSV file
		"""
		total_items = self.source_dataset.num_rows

		# We first collect all possible columns for the csv file, then
		# for each item make sure there is a value for all the columns (in the
		# second step)
		all_keys = self.source_dataset.get_item_keys()

		self.dataset.update_status("Converting file")
		staging_area = self.dataset.get_staging_area()
		with staging_area.joinpath('temp.ndjson').open("w") as output:
			for original_item, mapped_item in self.source_dataset.iterate_mapped_items(self):
				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while writing temporary results to file")

				# Flatten the dict
				item = flatten_dict(original_item)
				# Add any new keys to all_keys
				for field in item.keys():
					if field not in all_keys:
						all_keys.append(field)

				# Add mapped keys to flattened original item
				item.update(mapped_item)

				# Write this new json to our temp file
				output.write(json.dumps(item) + "\n")

		processed = 0
		# Create new CSV file
		with self.dataset.get_results_path().open("w", newline="") as output:
			writer = csv.DictWriter(output, fieldnames=all_keys)
			writer.writeheader()

			with staging_area.joinpath('temp.ndjson').open("r") as infile:
				for line in infile:
					if self.interrupted:
						raise ProcessorInterruptedException("Interrupted while writing results to file")

					item = json.loads(line)
					writer.writerow({key: item.get(key, "") for key in all_keys})
					processed += 1

				if processed % 100 == 0:
					self.dataset.update_status(
						f"Processed {processed}/{total_items} items")
					self.dataset.update_progress(processed / total_items)

		# done!
		self.dataset.update_status("Finished.")
		self.dataset.finish(num_rows=processed)
