"""
Generate bipartite user-hashtag graph of posts
"""
import re

from backend.abstract.processor import BasicProcessor
from backend.lib.helpers import UserInput

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class HashtagUserBipartiteGrapher(BasicProcessor):
	"""
	Generate bipartite user-hashtag graph of posts
	"""
	type = "bipartite-user-tag-network"  # job type ID
	category = "Networks"  # category
	title = "Bipartite Author-tag Network"  # title displayed in UI
	description = "Produces a bipartite graph based on co-occurence of (hash)tags and people. If someone wrote a post with a certain tag, there will be a link between that person and the tag. The more often they appear together, the stronger the link."  # description displayed in UI
	extension = "gdf"  # extension of result file, used internally and in UI

	datasources = ["instagram", "tumblr", "tiktok", "usenet", "parler"]

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
		all_users = {}
		pairs = {}
		posts = 1

		for post in self.iterate_csv_items(self.source_file):
			if posts % 25 == 0:
				self.dataset.update_status("Reading post %i..." % posts)
			posts += 1

			# create a list of tags
			if self.parent.parameters["datasource"] in ("instagram", "tiktok"):
				tags = post.get("tags", "").split(",")
				tags += [leading_hash.sub("", tag) for tag in post.get("hashtags", "").split(",")]

			elif self.parent.parameters["datasource"] == "tumblr":
				# Convert string of list to actual list
				tags = post.get("tags", None)
				if tags:
					# original format is ['tag1', 'tag2', ..., 'tagn'], so ignore brackets and '
					tags = [tag.strip()[1:-1] for tag in tags[1:-1].split(",")]
				else:
					tags = []

			elif self.parent.parameters["datasource"] == "usenet":
				if not post.get("groups"):
					continue

				tags = post.get("groups", "").split(",")

			# just in case
			tags = [tag.strip().replace(",", "").replace("\"", "'") for tag in tags]

			# To lowercase if so desired
			if self.parameters.get("to_lowercase"):
				tags = [tag.lower() for tag in tags]

			user = post.get("author")
			if not user:
				continue

			for tag in tags:
				# ignore empty tags
				if not tag:
					continue

				if tag not in all_tags:
					all_tags[tag] = 0
				all_tags[tag] += 1

				if user not in all_users:
					all_users[user] = 0
				all_users[user] += 1

				pair = sorted((tag, user))
				pair_key = "-_-".join(pair)

				if pair_key not in pairs:
					pairs[pair_key] = 0

				pairs[pair_key] += 1

		# write GDF file
		self.dataset.update_status("Writing to Gephi-compatible file")
		with self.dataset.get_results_path().open("w", encoding="utf-8") as results:
			results.write("nodedef>name VARCHAR,category VARCHAR,weight INTEGER\n")
			for tag in all_tags:
				results.write("'" + tag + "',hashtag,%i\n" % all_tags[tag])

			for user in all_users:
				results.write("'" + user + "',user,%i\n" % all_users[user])

			results.write("edgedef>tag VARCHAR, user VARCHAR, weight INTEGER\n")
			for pair in pairs:
				results.write(
					"'" + pair.split("-_-")[0] + "','" + pair.split("-_-")[1] + "',%i\n" % pairs[pair])

		self.dataset.finish(len(pairs))
