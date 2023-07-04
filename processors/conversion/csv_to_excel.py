"""
Convert a CSV file to Excel-compatible CSV
"""
import csv

from backend.lib.processor import BasicProcessor

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)

class ConvertCSVToMacExcel(BasicProcessor):
	"""
	Convert a CSV file to Excel-compatible CSV
	"""
	type = "convert-csv-excel"  # job type ID
	category = "Conversion"  # category
	title = "Convert to Excel-compatible CSV"  # title displayed in UI
	description = "Change a CSV file so it works with Microsoft Excel."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	@classmethod
	def is_compatible_with(cls, module=None, user=None):
		"""
		Determine if processor is compatible with dataset

		:param module: Module to determine compatibility with
		"""
		if module.type == cls.type:
			return False

		if module.get_extension() == "csv":
			return True
		elif module.get_extension() == "ndjson":
			return hasattr(module.get_own_processor(), "map_item")

	def process(self):
		"""
		This takes a CSV file as input and writes the same data as a JSON file
		"""
		posts = 0
		self.dataset.update_status("Converting posts")

		# painstaking empirical work has determined that this dialect is
		# compatible with the MacOS version of Microsoft Excel
		csv.register_dialect("excel-mac",
			delimiter = ";",
			doublequote = True,
			escapechar = None,
			lineterminator = "\r\n",
			quotechar = '"',
			quoting = csv.QUOTE_MINIMAL,
			skipinitialspace = False,
			strict = False
		)

		# recreate CSV file with the new dialect
		with self.dataset.get_results_path().open("w") as output:
			fieldnames = self.source_dataset.get_item_keys(self)

			writer = csv.DictWriter(output, fieldnames=fieldnames, dialect="excel-mac")
			writer.writeheader()

			for post in self.source_dataset.iterate_items(self):
				writer.writerow(post)
				posts += 1


		# done!
		self.dataset.update_status("Finished.")
		self.dataset.finish(num_rows=posts)

	@classmethod
	def get_csv_parameters(cls, csv_library):
		"""
		Returns CSV parameters if they are changed from 4CAT's defaults.
		"""
		csv_library.register_dialect("excel-mac",
			delimiter = ";",
			doublequote = True,
			escapechar = None,
			lineterminator = "\r\n",
			quotechar = '"',
			quoting = csv.QUOTE_MINIMAL,
			skipinitialspace = False,
			strict = False
		)

		return {"dialect": "excel-mac"}
