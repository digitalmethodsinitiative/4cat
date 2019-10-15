"""
Determine hatebase scores for posts
"""
import json
import re

from csv import DictReader, DictWriter

from backend.abstract.processor import BasicProcessor

import config


class HatebaseAnalyser(BasicProcessor):
	"""
	Identify hatebase-listed words in posts
	"""
	type = "hatebase-data"  # job type ID
	category = "Post metrics"  # category
	title = "Hatebase analysis"  # title displayed in UI
	description = "Analyse all posts' content with Hatebase, assigning a score for 'offensiveness' and a propability that the post contains hate speech."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	token_expires = 0
	token = ""

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with IDs and post bodies for all posts as well as a number of metrics
		derived from the hatebase database, e.g. number of matching items,
		how ambiguous the hatefulness is and the average 'offensiveness'.
		"""
		processed = 0
		parent = self.dataset.get_genealogy()[-2]

		with open(config.PATH_ROOT + "/backend/assets/hatebase.json") as hatebasedata:
			hatebase = json.loads(hatebasedata.read())

		hatebase = {term.lower(): hatebase[term] for term in hatebase}
		hatebase_regex = re.compile(r"\b(" + "|".join([re.escape(term) for term in hatebase]) + r")\b")

		with self.source_file.open() as input:
			reader = DictReader(input)
			processed = 0
			with self.dataset.get_results_path().open("w") as output:
				fieldnames = reader.fieldnames
				fieldnames += ("hatebase_num", "hatebase_num_ambiguous", "hatebase_num_unambiguous",
					"hatebase_terms", "hatebase_terms_ambiguous", "hatebase_terms_unambiguous",
					"hatebase_offensiveness_avg")

				writer = DictWriter(output, fieldnames=fieldnames)
				writer.writeheader()

				for post in reader:
					processed += 1
					self.dataset.update_status("Processing post %i" % processed)
					row = {**post, **{
						"hatebase_num": 0,
						"hatebase_num_ambiguous": 0,
						"hatebase_num_unambiguous": 0,
						"hatebase_terms": "",
						"hatebase_terms_ambiguous": "",
						"hatebase_terms_unambiguous": "",
						"hatebase_offensiveness_avg": 0,
					}}

					terms = []
					terms_ambig = []
					terms_unambig = []
					for term in hatebase_regex.findall(post["body"].lower()):
						terms.append(term)
						row["hatebase_num"] += 1
						if hatebase[term]["is_unambiguous"]:
							row["hatebase_num_unambiguous"] += 1
							terms_unambig.append(term)
						else:
							row["hatebase_num_ambiguous"] += 1
							terms_ambig.append(term)

						if hatebase[term]["average_offensiveness"]:
							row["hatebase_offensiveness_avg"] += hatebase[term]["average_offensiveness"]

					row["hatebase_terms"] = ",".join(terms)
					row["hatebase_terms_ambiguous"] = ",".join(terms_ambig)
					row["hatebase_terms_unambiguous"] = ",".join(terms_unambig)

					if len(terms) > 0:
						row["hatebase_offensiveness_avg"] = int(int(row["hatebase_offensiveness_avg"]) / len(terms))

					writer.writerow(row)

		self.dataset.update_status("Finished")
		self.dataset.finish(processed)
