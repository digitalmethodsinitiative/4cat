"""
Determine hatebase scores for posts
"""
import json
import csv
import re

from backend.lib.processor import BasicProcessor
from common.lib.helpers import UserInput
from common.lib.exceptions import ProcessorInterruptedException
from common.config_manager import config

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)


class HatebaseAnalyser(BasicProcessor):
	"""
	Identify hatebase-listed words in posts
	"""
	type = "hatebase-data"  # job type ID
	category = "Post metrics"  # category
	title = "Hatebase analysis"  # title displayed in UI
	description = "Assign scores for 'offensiveness' and hate speech propability to each post by using Hatebase."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	token_expires = 0
	token = ""

	references = [
		"[Hatebase.org](https://hatebase.org)"
	]

	options = {
		"language": {
			"type": UserInput.OPTION_CHOICE,
			"default": "en",
			"options": {
				"en": "English",
				"it": "Italian"
			},
			"help": "Language"
		},
		"columns": {
			"type": UserInput.OPTION_TEXT,
			"help": "Columns to analyse",
			"default": "body",
			"tooltip": "The content of these columns will be analysed for presence of hatebase-listed words."
		}
	}

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with IDs and post bodies for all posts as well as a number of metrics
		derived from the hatebase database, e.g. number of matching items,
		how ambiguous the hatefulness is and the average 'offensiveness'.
		"""

		# determine what vocabulary to use
		language = self.parameters.get("language")
		columns = self.parameters.get("columns")

		if not columns:
			self.dataset.update_status("No columns selected; no data analysed.", is_final=True)
			self.dataset.finish(0)
			return

		# read and convert to a way we can easily match whether any word occurs
		with config.get('PATH_ROOT').joinpath(f"common/assets/hatebase/hatebase-{language}.json").open() as hatebasedata:
			hatebase = json.loads(hatebasedata.read())

		hatebase = {term.lower(): hatebase[term] for term in hatebase}
		hatebase_regex = re.compile(r"\b(" + "|".join([re.escape(term) for term in hatebase]) + r")\b")

		processed = 0
		with self.dataset.get_results_path().open("w") as output:
			fieldnames = self.source_dataset.get_item_keys(self)
			fieldnames += ("hatebase_num", "hatebase_num_ambiguous", "hatebase_num_unambiguous",
					"hatebase_terms", "hatebase_terms_ambiguous", "hatebase_terms_unambiguous",
					"hatebase_offensiveness_avg")

			writer = csv.DictWriter(output, fieldnames=fieldnames)
			writer.writeheader()

			for post in self.source_dataset.iterate_items(self):
				# stop processing if worker has been asked to stop
				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while processing posts")

				processed += 1
				if processed % 1000 == 0:
					self.dataset.update_status("Processing post %i" % processed)
					self.dataset.update_progress(processed / self.source_dataset.num_rows)
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

				post_text = ' '.join([str(post.get(c, "")).lower() for c in columns])
				for term in hatebase_regex.findall(post_text):
					if hatebase[term]["plural_of"]:
						if hatebase[term]["plural_of"] in terms:
							continue
						elif hatebase[term]["plural_of"] in hatebase:
							term = hatebase[term]["plural_of"]

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

				try:
					writer.writerow(row)
				except ValueError as e:
					self.log.error(str(e))
					self.dataset.update_status("Cannot write results. Your input file may contain invalid CSV data.")
					self.dataset.finish(0)
					return

		self.dataset.update_status("Finished")
		self.dataset.finish(processed)

	@classmethod
	def get_options(cls, parent_dataset=None, user=None):
		"""
		Get processor options

		This method by default returns the class's "options" attribute, or an
		empty dictionary. It can be redefined by processors that need more
		fine-grained options, e.g. in cases where the availability of options
		is partially determined by the parent dataset's parameters.

		:param DataSet parent_dataset:  An object representing the dataset that
		the processor would be run on
		:param User user:  Flask user the options will be displayed for, in
		case they are requested for display in the 4CAT web interface. This can
		be used to show some options only to privileges users.
		"""
		options = cls.options

		if parent_dataset and parent_dataset.get_columns():
			columns = parent_dataset.get_columns()
			options["columns"]["type"] = UserInput.OPTION_MULTI_SELECT
			options["columns"]["options"] = {v: v for v in columns}
			options["columns"]["default"] = "body" if "body" in columns else sorted(columns).pop()

		return options
