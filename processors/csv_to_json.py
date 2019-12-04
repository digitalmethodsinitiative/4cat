"""
Convert a CSV file to JSON
"""
import json

from csv import DictReader

from backend.abstract.processor import BasicProcessor


class ConvertCSVToJSON(BasicProcessor):
	"""
	Convert a CSV file to JSON
	"""
	type = "convert-csv"  # job type ID
	category = "Conversion"  # category
	title = "Convert to JSON"  # title displayed in UI
	description = "Convert a CSV file to JSON"  # description displayed in UI
	extension = "json"  # extension of result file, used internally and in UI

	# all post-processors with CSV output
	accepts = ["search", "collocations", "debate_metrics", "quote-ranker", "tfidf", "thread-metadata",
			   "count-countries", "top-images", "url-extractor", "extract-usernames", "vector-ranker",
			   "count-words", "youtube-metadata", "attribute-frequencies", "count-posts"]

	input = "csv"
	output = "json"

	def process(self):
		"""
		This takes a CSV file as input and writes the same data as a JSON file
		"""
		posts = 0
		self.dataset.update_status("Converting posts")

		with self.source_file.open(encoding="utf-8") as source:
			csv = DictReader(source)

			# we write to file per row, instead of json.dumps()ing all of it at
			# once, since else we risk having to keep a lot of data in memory,
			# and this buffers one row at most
			with self.dataset.get_results_path().open("w") as output:
				output.write("[")
				for post in csv:
					posts += 1

					if posts > 1:
						output.write(",")

					output.write(json.dumps(post))
				output.write("]")

		self.dataset.update_status("Finished.")
		self.dataset.finish(num_rows=posts)
