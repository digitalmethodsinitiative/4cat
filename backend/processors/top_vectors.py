"""
Rank top vernacular in tokens
"""
import zipfile
import pickle
import shutil
import csv

from backend.lib.helpers import UserInput
from backend.abstract.processor import BasicProcessor


class VectorRanker(BasicProcessor):
	"""
	Rank vectors over time
	"""
	type = "vector-ranker"  # job type ID
	category = "Post metrics" # category
	title = "Top vectors"  # title displayed in UI
	description = "Ranks most used tokens per token set. Reveals most-used words and/or most-used vernacular per time period. Limited to 100 most-used tokens."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	accepts = ["vectorise-tokens"]

	options = {
		"top": {
			"type": UserInput.OPTION_TEXT,
			"default": 100,
			"help": "Cut-off for top list"
		},
		"amount": {
			"type": UserInput.OPTION_TOGGLE,
			"default": False,
			"help": "Include number of occurrences"
		}
	}

	def process(self):
		"""
		Reads vector set and creates a CSV with ranked vectors
		"""

		# prepare staging area
		results_path = self.dataset.get_temporary_path()
		results_path.mkdir()

		self.dataset.update_status("Processing token sets")
		vector_paths = []

		# go through all archived token sets and vectorise them
		results = []

		def file_to_timestamp(file):
			"""
			Get comparable datestamp value for token file

			Token files are named YYYY-m.pb. This function converts that to a
			YYYYmm string, then that string to an int, so that it may be
			compared for sorting chronologically.

			:param str file:  File name
			:return int:  Comparable datestamp
			"""
			stem = file.split("/")[-1].split(".")[0].split("-")
			try:
				return int(stem[0] + stem[1].zfill(2))
			except ValueError:
				return 0

		with zipfile.ZipFile(self.source_file, "r") as token_archive:
			vector_sets = sorted(token_archive.namelist(), key=file_to_timestamp)
			index = 0

			for vector_set in vector_sets:
				index += 1
				vector_set_name = vector_set.split("/")[-1]  # we don't need the full path
				self.dataset.update_status("Processing token set %i/%i" % (index, len(vector_sets)))

				# temporarily extract file (we cannot use ZipFile.open() as it doesn't support binary modes)
				temp_path = results_path.joinpath(vector_set_name)
				token_archive.extract(vector_set_name, results_path)
				with temp_path.open("rb") as binary_tokens:
					# these were saved as pickle dumps so we need the binary mode
					vectors = pickle.load(binary_tokens)
				temp_path.unlink()

				if len(results) == 0:
					results.append([])

				results[0].append(vector_set_name.split(".")[0])
				if self.parameters["amount"]:
					results[0].append("occurrences")

				for row in range(1, 102):
					if len(results) < (row + 1):
						results.append([])

					if row >= len(vectors):
						results[row].append("")
						if self.parameters["amount"]:
							results[row].append("")
					else:
						results[row].append(vectors[row][0])
						if self.parameters["amount"]:
							results[row].append(vectors[row][1])

		# delete temporary files and folder
		shutil.rmtree(results_path)

		# truncate results as needed
		try:
			cutoff = int(self.parameters.get("top", 100))
		except TypeError:
			cutoff = 10

		results = results[0:cutoff]

		# done!
		self.dataset.update_status("Writing results file")
		with open(self.dataset.get_results_path(), "w", encoding="utf-8") as output:
			writer = csv.writer(output)
			for row in results:
				writer.writerow(row)

		self.dataset.update_status("Finished")
		self.dataset.finish(len(results))
