"""
Rank top vernacular in tokens
"""
import pickle
import csv
import json

from common.lib.helpers import UserInput, convert_to_int
from backend.abstract.processor import BasicProcessor

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

class VectorRanker(BasicProcessor):
	"""
	Rank vectors over time
	"""
	type = "vector-ranker"  # job type ID
	category = "Post metrics" # category
	title = "Top vectors"  # title displayed in UI
	description = "Ranks most used tokens per token set. Reveals most-used words and/or most-used vernacular per time period. Limited to 100 most-used tokens."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	options = {
		"top": {
			"type": UserInput.OPTION_TEXT,
			"default": 25,
			"help": "Cut-off for top list"
		},
		"top-style": {
			"type": UserInput.OPTION_CHOICE,
			"default": "per-item",
			"options": {"per-item": "per interval (separate ranking per interval)", "overall": "overall (per-interval ranking for overall top items)"},
			"help": "Determine top items",
			"tooltip": "'Overall' will first determine the most prevalent vectors across all intervals, then calculate top vectors per interval using this as a shortlist."
		},
	}

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor on token vectors

		:param module: Dataset or processor to determine compatibility with
		"""
		return module.type == "vectorise-tokens"

	def process(self):
		"""
		Reads vector set and creates a CSV with ranked vectors
		"""
		self.dataset.update_status("Processing token sets")

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
			except (ValueError, IndexError):
				return 0

		results = []

		# truncate results as needed
		rank_style = self.parameters.get("top-style")
		cutoff = convert_to_int(self.parameters.get("top"))

		# now rank the vectors by most prevalent per "file" (i.e. interval)
		overall_top = {}
		index = 0
		for vector_file in self.iterate_archive_contents(self.source_file):
			# we support both pickle and json dumps of vectors
			vector_unpacker = pickle if vector_file.suffix == "pb" else json

			index += 1
			vector_set_name = vector_file.stem  # we don't need the full path
			self.dataset.update_status("Processing token set %i (%s)" % (index, vector_set_name))

			with vector_file.open("rb") as binary_tokens:
				# these were saved as pickle dumps so we need the binary mode
				vectors = vector_unpacker.load(binary_tokens)

			vectors = sorted(vectors, key=lambda x: x[1], reverse=True)
				
			# for overall ranking we need the full vector space per interval
			# because maybe an overall top-ranking vector is at the bottom
			# in this particular interval - we'll truncate the top list at
			# a later point in that case. Else, truncate it here
			if rank_style == "per-item":
				vectors = vectors[0:cutoff]

			for vector in vectors:
				if not vector[0].strip():
					continue

				results.append({"date": vector_set_name.split(".")[0], "item": vector[0], "value": vector[1]})

				if vector[0] not in overall_top:
					overall_top[vector[0]] = 0

				overall_top[vector[0]] += int(vector[1])

		# this eliminates all items from the results that were not in the
		# *overall* top-occuring items. This only has an effect when vectors
		# were generated for multiple intervals
		if rank_style == "overall":
			overall_top = {item: overall_top[item] for item in sorted(overall_top, key=lambda x: overall_top[x], reverse=True)[0:cutoff]}
			filtered_results = []
			for item in results:
				if item["item"] in overall_top:
					filtered_results.append(item)

			results = filtered_results

		# done!
		self.dataset.update_status("Writing results file")
		with open(self.dataset.get_results_path(), "w", encoding="utf-8") as output:
			writer = csv.DictWriter(output, fieldnames = ("date", "item", "value"))
			writer.writeheader()
			for row in results:
				writer.writerow(row)

		self.dataset.update_status("Finished")
		self.dataset.finish(len(results))
