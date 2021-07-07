"""
Generate co-link network of URLs in posts
"""
import re
import csv

from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput, gdf_escape

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

	options = {
		"to_lowercase": {
			"type": UserInput.OPTION_TOGGLE,
			"default": True,
			"help": "Convert the tags to lowercase",
			"tooltip": "Converting the tags to lowercase can help in removing duplicate edges between nodes"
		}
	}

	@classmethod
	def is_compatible_with(cls, dataset=None):
		"""
		Allow processor on datasets containing a tags column

		:param DataSet dataset:  Dataset to determine compatibility with
		"""
		if dataset.type == "twitterv2-search":
			# ndjson, difficult to sniff
			return True
		elif dataset.get_results_path().suffix == ".csv" and dataset.get_results_path().exists():
			# csv can just be sniffed for the presence of a column
			with dataset.get_results_path().open(encoding="utf-8") as infile:
				reader = csv.DictReader(infile)
				try:
					return bool(set(reader.fieldnames) & {"tags", "hashtags", "groups"})
				except (TypeError, ValueError):
					return False
		else:
			return False

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
		pair_sep = "!@!@!@!"

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

				if not post.get(tag_field):
					continue

				for tag in post.get(tag_field, "").split(","):
					tags.append(tag.strip())

			# Clean up the tags
			to_lowercase = self.parameters.get("to_lowercase")
			tags = [self.sanitise(tag, to_lowercase=to_lowercase) for tag in tags]

			for tag in tags:

				# ignore empty tags
				if not tag:
					continue

				if tag not in list(all_tags.keys()):
					all_tags[tag] = 1
				else:
					all_tags[tag] += 1

				for co_tag in tags:
					
					if co_tag == tag or not co_tag:
						continue

					pair = sorted((tag, co_tag))
					pair_key = pair_sep.join(pair)

					if pair_key not in pairs:
						pairs[pair_key] = 1
					else:
						pairs[pair_key] += 1

		# write GDF file
		self.dataset.update_status("Writing to Gephi-compatible file")
		with self.dataset.get_results_path().open("w", encoding="utf-8") as results:
			results.write("nodedef>name VARCHAR,weight INTEGER\n")
			for tag_name, tag_value in all_tags.items():
				results.write("%s,%i\n" % (gdf_escape(tag_name), tag_value))

			results.write("edgedef>node1 VARCHAR,node2 VARCHAR,weight INTEGER\n")
			for pair, weight in pairs.items():
				pair = pair.split(pair_sep)
				results.write("%s,%s,%i\n" % (gdf_escape(pair[0]), gdf_escape(pair[1]), weight))

		self.dataset.finish(len(pairs))

	def sanitise(self, tag, to_lowercase):
		"""
		Do some conversion of a tag.
		Mostly to evade encoding issues.

		:param tag, str:			The tag string to sanitise.
		:param to_lowercase, bool:	Whether to convert the tag to lowercase.

		"""

		tag = tag.strip()
		tag = tag.replace(",","")
		
		# ' quote chars gan give encoding issues in the case of sigma JS.
		# So convert to the safer ’
		tag = tag.replace("\"","”")
		tag = tag.replace("\'","’")
		
		if to_lowercase:
			tag = tag.lower()

		return tag