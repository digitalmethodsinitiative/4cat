"""
Generate co-link network of URLs in posts
"""
import re

from backend.abstract.processor import BasicProcessor
from backend.lib.helpers import UserInput

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

class CoTagger(BasicProcessor):
	"""
	Generate co-tag network
	"""
	type = "cotag-network"  # job type ID
	category = "Networks"  # category
	title = "Co-tag network"  # title displayed in UI
	description = "Create a Gephi-compatible network comprised of all tags appearing in the dataset, with edges between " \
				  "all tags used together on an item. Edges are weighted by the amount of co-tag occurrences; nodes are" \
				  "weighted by the frequency of the tag."  # description displayed in UI
	extension = "gdf"  # extension of result file, used internally and in UI

	datasources = ["instagram", "tumblr", "tiktok", "usenet", "parler", "custom"]

	input = "csv:tags|hashtags|groups"
	output = "gdf"

	options = {
		"to_lowercase": {
			"type": UserInput.OPTION_TOGGLE,
			"default": True,
			"help": "Convert the tags to lowercase",
			"tooltip": "Converting the tags to lowercase can help in removing duplicate edges between nodes"
		}
	}

	def process(self):
		"""
		Generates a GDF co-tag graph.

		Tags should be contained in the results file in a column named 'tags'
		or 'hashtags', and contained therein should be a list of tags in
		plain text separated by commas.
		"""
		leading_hash = re.compile(r"^#")

		all_tags = {}
		pairs = {}
		posts = 1
		tag_field = None

		for post in self.iterate_items(self.source_file):
			self.dataset.update_status("Reading post %i..." % posts)
			posts += 1

			# create a list of tags
			if self.source_dataset.parameters["datasource"] in ("instagram", "tiktok"):
				if not post.get("hashtags", None):
					continue

				tags = post.get("tags", "").split(",")
				tags += [leading_hash.sub("", tag) for tag in post.get("hashtags", "").split(",")]

			elif self.source_dataset.parameters["datasource"] == "tumblr":
				if not post.get("tags", None):
					continue

				# Convert string of list to actual list
				tags = post.get("tags", "").split(",")

				if not tags:
					tags = []
			elif self.source_dataset.parameters["datasource"] == "usenet":
				if not post.get("groups"):
					continue

				tags = post.get("groups", "").split(",")
			else:
				tags = []
				if not tag_field:
					tag_field = "tags" if "tags" in post else "hashtags"
					if tag_field not in post:
						self.dataset.update_status("Dataset has no 'hashtags' or 'tags' column, cannot analyse tag usage", is_final=True)
						return

				for tag in post.get(tag_field, "").split(","):
					tags.append(tag.strip())

			# just in case
			tags = [tag.strip().replace(",","").replace("\"","'") for tag in tags]

			# To lowercase if so desired
			if self.parameters.get("to_lowercase"):
				tags = [tag.lower() for tag in tags]

			for tag in tags:
				# ignore empty tags
				if not tag:
					continue

				if tag not in all_tags:
					all_tags[tag] = 0
				all_tags[tag] += 1

				for co_tag in tags:
					
					if co_tag == tag or not co_tag:
						continue

					pair = sorted((tag, co_tag))
					pair_key = "-_-".join(pair)

					if pair_key not in pairs:
						pairs[pair_key] = 0

					pairs[pair_key] += 1

		# write GDF file
		self.dataset.update_status("Writing to Gephi-compatible file")
		with self.dataset.get_results_path().open("w", encoding="utf-8") as results:
			results.write("nodedef>name VARCHAR,weight INTEGER\n")
			for tag in all_tags:
				results.write("'" + tag + "',%i\n" % all_tags[tag])

			results.write("edgedef>node1 VARCHAR, node2 VARCHAR, weight INTEGER\n")
			for pair in pairs:
				results.write(
					"'" + pair.split("-_-")[0] + "','" + pair.split("-_-")[1] + "',%i\n" % pairs[pair])

		self.dataset.finish(len(pairs))
