"""
Generate bipartite user-hashtag graph of posts
"""
import csv
import re

from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput, gdf_escape

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
	description = "Produces a bipartite graph based on co-occurence of (hash)tags and people. If someone wrote a post with a certain tag, there will be a link between that person and the tag. The more often they appear together, the stronger the link. Tag nodes are weighed on how often they occur. User nodes are weighed on how many posts they've made."  # description displayed in UI
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
				except TypeError:
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
		all_users = {}
		pairs = {}
		posts = 1
		tag_field = None

		for post in self.iterate_items(self.source_file):
			if posts % 25 == 0:
				self.dataset.update_status("Reading post %i..." % posts)
			posts += 1

			# create a list of tags
			if self.source_dataset.parameters["datasource"] in ("instagram", "tiktok", "tumblr"):
				tags = post.get("tags", "").split(",")
				tags += [leading_hash.sub("", tag) for tag in post.get("hashtags", "").split(",")]

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
			tags = [tag.strip().replace(",", "").replace("\"", "'") for tag in tags]

			# To lowercase if so desired
			if self.parameters.get("to_lowercase"):
				tags = [tag.lower() for tag in tags]

			user = post.get("author")
			if not user:
				continue
			
			# Weigh users on the amount of posts they've made
			if user not in all_users:
				all_users[user] = 1
			else:
				all_users[user] += 1

			for tag in tags:
				# ignore empty tags
				if not tag:
					continue

				if tag not in all_tags:
					all_tags[tag] = 1
				else:
					all_tags[tag] += 1

				pair = [user, tag]
				pair_key = "-_-".join(pair)

				if pair_key not in pairs:
					pairs[pair_key] = 1
				else:
					pairs[pair_key] += 1

		# write GDF file
		self.dataset.update_status("Writing to Gephi-compatible file")
		with self.dataset.get_results_path().open("w", encoding="utf-8") as results:
			results.write("nodedef>name VARCHAR,category VARCHAR,weight INTEGER\n")
			for tag in all_tags:
				results.write(gdf_escape(tag) + ",hashtag,%i\n" % all_tags[tag])

			for user in all_users:
				results.write(gdf_escape(user) + ",user,%i\n" % all_users[user])

			results.write("edgedef>user VARCHAR, tag VARCHAR, weight INTEGER, directed BOOLEAN\n")
			for pair in pairs:
				pair_weight = pairs[pair]
				pair = pair.split("-_-")
				results.write(
					gdf_escape(pair[0]) + "," + gdf_escape(pair[1]) + ",%i,TRUE\n" % pair_weight)

		self.dataset.finish(len(pairs))
