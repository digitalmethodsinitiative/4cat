"""
Convert a CSV file to MacOS Excel-compatible CSV
"""
import csv

from backend.abstract.processor import BasicProcessor

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

class ConvertCSVToMacExcel(BasicProcessor):
	"""
	Convert a CSV file to MacOS Excel-compatible CSV
	"""
	type = "convert-csv-excel-mac"  # job type ID
	category = "Conversion"  # category
	title = "Convert to MacOS Excel-compatible CSV"  # title displayed in UI
	description = "Convert a CSV file to a format that is compatible with Microsoft Excel for MacOS."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	# all post-processors with CSV output
	accepts = ["search", "collocations", "count-posts", "debate_metrics", "get-entities",
			   "extract-nouns", "hatebase-data", "penelope-semanticframe", "quote-ranker",
			   "tfidf", "thread-metadata", "sentence-split", "hatebase-frequencies",
			   "count-countries", "top-images", "url-extractor", "extract-usernames", "vector-ranker",
			   "count-words", "youtube-metadata", "attribute-frequencies", "count-posts"]

	input = "csv"
	output = "csv"

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
		with self.source_file.open(encoding="utf-8") as source:
			reader = csv.DictReader(source)
			with self.dataset.get_results_path().open("w") as output:
				writer = csv.DictWriter(output, fieldnames=reader.fieldnames, dialect="excel-mac")
				writer.writeheader()

				for post in reader:
					writer.writerow(post)
					posts += 1


		# done!
		self.dataset.update_status("Finished.")
		self.dataset.finish(num_rows=posts)
