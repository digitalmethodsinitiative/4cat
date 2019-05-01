"""
Rank top vernacular in tokens
"""
import zipfile
import pickle
import shutil
import csv
import os

from backend.lib.helpers import UserInput
from backend.abstract.postprocessor import BasicPostProcessor


class VectorRanker(BasicPostProcessor):
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
		dirname_base = self.query.get_results_path().replace(".", "") + "-vectors"
		dirname = dirname_base
		index = 1
		while os.path.exists(dirname):
			dirname = dirname_base + "-" + str(index)
			index += 1

		os.mkdir(dirname)

		self.query.update_status("Processing token sets")
		vector_paths = []

		# go through all archived token sets and vectorise them
		results = []
		with zipfile.ZipFile(self.source_file, "r") as token_archive:
			vector_sets = token_archive.namelist()
			index = 0

			for vector_set in vector_sets:
				index += 1
				vector_set_name = vector_set.split("/")[-1]  # we don't need the full path
				self.query.update_status("Processing token set %i/%i" % (index, len(vector_sets)))

				# temporarily extract file (we cannot use ZipFile.open() as it doesn't support binary modes)
				temp_path = dirname + "/" + vector_set_name
				token_archive.extract(vector_set_name, dirname)
				with open(temp_path, "rb") as binary_tokens:
					# these were saved as pickle dumps so we need the binary mode
					vectors = pickle.load(binary_tokens)
				os.unlink(temp_path)

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
		shutil.rmtree(dirname)

		# done!
		self.query.update_status("Writing results file")
		with open(self.query.get_results_path(), "w", encoding="utf-8") as output:
			writer = csv.writer(output)
			for row in results:
				writer.writerow(row)

		self.query.update_status("Finished")
		self.query.finish(len(results))
