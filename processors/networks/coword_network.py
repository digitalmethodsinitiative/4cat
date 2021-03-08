"""
Generate co-word network of word collocations
"""
import re

from backend.abstract.processor import BasicProcessor
from backend.lib.helpers import UserInput

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

class CowordNetworker(BasicProcessor):
	"""
	Generate co-word network
	"""
	type = "coword-network"  # job type ID
	category = "Networks"  # category
	title = "Co-word network"  # title displayed in UI
	description = "Create a Gephi-compatible network comprised of co-words, with edges between " \
				  "words that appear close to each other. Edges and nodes are weighted by the " \
				  "amount of co-word occurrences."  # description displayed in UI
	extension = "gdf"  # extension of result file, used internally and in UI

	accepts = ["collocations"]

	input = "csv:word1|word2|value"
	output = "gdf"

	def process(self):
		"""
		Generates a GDF co-tag graph.

		Words should be contained in the results file in a column named 'word_1' and 'word_2'.
		"""

		# Since there's no suitable way to show time 
		# This processor only works on overall collocations.
		date_value = self.dataset.get_genealogy()[1].parameters["docs_per"]

		if date_value != "all":
			self.dataset.update_status("To use this module, \"Produce documents per\" in the tokeniser should be set to \"Overall\".")
			self.dataset.finish(-1)
			return

		pairs = {}
		all_words = []
		row_count = 1

		for row in self.iterate_items(self.source_file):
			self.dataset.update_status("Reading co-word pair %i..." % row_count)
			row_count += 1

			words = [row["word_1"], row["word_2"]]
			all_words += words
			pair = sorted(words)
			pair_key = "-_-".join(pair)
			pairs[pair_key] = int(row["value"])

		if not pairs:
			self.dataset.finish(-1)

		# write GDF file
		self.dataset.update_status("Writing to Gephi-compatible file")
		with self.dataset.get_results_path().open("w", encoding="utf-8") as results:
			results.write("nodedef>name VARCHAR,weight INTEGER\n")

			all_words = list(set(all_words))

			for word in all_words:
				results.write("'" + word + "',%i\n" % 1)

			results.write("edgedef>node1 VARCHAR, node2 VARCHAR, weight INTEGER\n")
			for pair in pairs:
				results.write(
					"'" + pair.split("-_-")[0] + "','" + pair.split("-_-")[1] + "',%i\n" % pairs[pair])

		self.dataset.finish(len(pairs))