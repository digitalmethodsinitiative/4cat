"""
Convert a NDJSON file to CSV
"""
import csv
import json

from common.lib.helpers import flatten_dict
from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
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
	description = "Change a NDJSON file to a CSV file."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Determine if processor is compatible with dataset

		:param module: Dataset or processor to determine compatibility with
		"""
		if module.get_extension() == "ndjson":
			return True

	def process(self):
		"""
		This takes a NDJSON file as input, flattens the dictionaries, and writes the same data as a CSV file
		"""
		posts = 0
		self.dataset.update_status("Converting posts")

		# First create a temporary NDJSON file and collect all possible keys
		# I cannot think of a way to do this without looping twice, but this way
		# we do not have to flatten the dictionaries twice
		all_keys = set()
		staging_area = self.dataset.get_staging_area()
		with staging_area.joinpath('temp.ndjson').open("w") as output:

			# Check if source_dataset has map_item function
			if hasattr(self.source_dataset.get_own_processor(), "map_item"):
				use_item_mapper = True
				item_mapper = self.source_dataset.get_own_processor().map_item
				# Add these specific keys
				[all_keys.add(key) for key in self.source_dataset.get_item_keys()]
			else:
				use_item_mapper = False

			for post in self.source_dataset.iterate_items(self, bypass_map_item=True):
				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while writing temporary results to file")

				# Flatten the dict
				item = flatten_dict(post)
				# Add any new keys to all_keys
				[all_keys.add(key) for key in item.keys()]

				if use_item_mapper:
					#then add that shit too
					item.update(item_mapper(post))

				# Write this new json to our temp file
				output.write(json.dumps(item) + "\n")


		# Create CSV file with the new dialect
		with self.dataset.get_results_path().open("w") as output:
			writer = csv.DictWriter(output, fieldnames=all_keys, lineterminator='\n')
			writer.writeheader()

			with staging_area.joinpath('temp.ndjson').open("r") as infile:
				for line in infile:
					if self.interrupted:
						raise ProcessorInterruptedException("Interrupted while writing results to file")
					item = json.loads(line)
					writer.writerow(item)
					posts += 1

		# done!
		self.dataset.update_status("Finished.")
		self.dataset.finish(num_rows=posts)
