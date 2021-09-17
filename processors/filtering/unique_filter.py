"""
Filter by unique posts
"""
import hashlib
import csv

from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)


class UniqueFilter(BasicProcessor):
	"""
	Retain only posts matching a given lexicon
	"""
	type = "unique-filter"  # job type ID
	category = "Filtering"  # category
	title = "Filter for unique posts"  # title displayed in UI
	description = "Retain only posts with unique post bodies. Only keeps the first encounter of a text. Useful for filtering spam. This creates a new, separate dataset you can run analyses on."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	# the following determines the options available to the user via the 4CAT
	# interface.
	options = {
		"case_sensitive": {
			"type": UserInput.OPTION_TOGGLE,
			"help": "Case sensitive",
			"default": False,
			"tooltip": "Check to consider posts with different capitals as different."
		}
	}

	def process(self):
		"""
		Reads a CSV file, hashes the posts, and only keeps those it didn't encounter yet.
		"""

		# now for the real deal
		self.dataset.update_status("Reading source file")

		# keep some stats
		processed = 0
		unique = 0

		hashes = set()

		# iterate through posts and see if they match
		with self.dataset.get_results_path().open("w", encoding="utf-8") as output:
			# get header row, we need to copy it for the output
			fieldnames = self.get_item_keys(self.source_file)

			# start the output file
			writer = csv.DictWriter(output, fieldnames=fieldnames)
			writer.writeheader()

			# iterate through posts and see if they match
			for post in self.iterate_items(self.source_file):

				if not post.get("body", None):
					continue

				body = post["body"].strip()
				if not self.parameters.get("case_sensitive", False):
					body = body.lower()

				hash_object = hashlib.md5(body.encode("utf-8"))
				md5_hash = hash_object.hexdigest()

				if md5_hash not in hashes:
					writer.writerow(post)
					unique += 1

				hashes.add(md5_hash)

				if processed % 2500 == 0:
					self.dataset.update_status("Processed %i posts (%i unique)" % (processed, unique))

				processed += 1

		self.dataset.update_status("New dataset created with %i matching item(s)" % unique, is_final=True)
		self.dataset.finish(unique)

	def after_process(self):
		super().after_process()

		# Request standalone
		self.create_standalone()
