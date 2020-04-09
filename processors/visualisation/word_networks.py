"""
Create a network of word relations
"""
import json
import random

import config

from pathlib import Path

from backend.lib.helpers import UserInput
from backend.abstract.processor import BasicProcessor

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

class word_networks(BasicProcessor):
	"""
	Generate a word embedding model from tokenised text.
	"""

	type = "word-networks"  # job type ID
	category = "Text analysis"  # category
	title = "Word networks"  # title displayed in UI
	description = "A graph of source and target words."  # description displayed in UI
	extension = "html"  # extension of result file, used internally and in UI
	accepts = ["word-embeddings-neighbours"]  # query types this post-processor accepts as input
	preview_allowed = False # Will slow down the page too much

	input = "csv:source_word,target_word,weight,date"
	output = "html"

	options = {
		"highlight": {
			"type": UserInput.OPTION_TEXT,
			"default": "",
			"options": {
				"highlight": ""
			},
			"help": "Highlight these words in the network"
		}
	}

	def process(self):
		"""
		Create a HTML file with a network of word pairs.
		Only works for sets of two for now (so trigram networks are not supported).

		"""

		# Get json data to use in a graph
		self.dataset.update_status("Generating graph data")
		data = self.generate_json(self.source_file)
		
		# Return empty when there's no results
		if not data:
			self.dataset.finish(-1)
			return

		self.dataset.update_status("Generating HTML file")

		# We need to use absolute URLs in the generated HTML, because they
		# may be downloaded (ideally they'd be fully self-contained, but that
		# would lead to very big files). So determine what URL we can use to
		# link to 4CAT's server in the generated HTML.
		if config.FlaskConfig.SERVER_HTTPS:
			server_url = "https://" + config.FlaskConfig.SERVER_NAME
		else:
			server_url = "http://" + config.FlaskConfig.SERVER_NAME

		# Generate a html file based on the retreived json data
		with open(config.PATH_ROOT + "/processors/visualisation/word_networks.html") as template:
			output = template.read().replace("**json**", json.dumps(data)).replace("**server**", server_url)

		# Write HTML file
		with self.dataset.get_results_path().open("w", encoding="utf-8") as output_file:
			output_file.write(output)

		# Finish
		self.dataset.update_status("Finished")
		self.dataset.finish(len(output))

	def generate_json(self, source_file):
		"""
		Generates a sigma.js compatible JSON object to make a network graph

		"""

		networks = {}

		current_date = ""

		node_id = 0
		edge_id = 0

		# Make different networks for different dates in the csv, like '2016-11' or 'overall'
		date_network = {}

		# So we don't add duplicates
		nodes_added = []
		edges_added = []

		# Possible words to highlight
		highlight_words = self.parameters.get("highlight")
		if highlight_words:
			highlight_words = [highlight_word for highlight_word in str(highlight_words).split(",")]

		# Go through the source csv
		for word_pair in self.iterate_csv_items(self.source_file):
			
			# Check if this is a new date, and if so, add it as a new list
			if word_pair["date"] != current_date:
 
				# Add the existing network if it exists (i.e. if we're processing a "current_date")
				if current_date and date_network:
					networks[current_date] = date_network
				
				# Empty the dict for the next round
				date_network = {"nodes": [], "edges": []}
				nodes_added = []
				edges_added = []

				current_date = word_pair["date"]

			# Set the source and target word
			source_word = word_pair["source_word"]
			target_word = word_pair["target_word"]

			# Use this to loop through both words
			source_and_target = [source_word, target_word]

			# Used for edge weights
			weight = word_pair.get("weight")
			if weight:
				weight = float(weight)
				if weight < 1: # Increase edge size for < numbers
					weight = weight * 10
				weight = int(weight)
			if not weight:
				weight = 1

			# Add nodes, if not already added
			for i, word in enumerate(source_and_target):

				word_type = "source" # Used for indexing the right column node size
				if i == 1:
					word_type = "target"

				if word not in nodes_added:
					# Node attributes
					node = {}
					node["id"] = word # We're using the word as an ID here, since it may only appear once anyway.
					node["label"] = word
					node["x"] = random.randrange(1, 20)
					node["y"] = random.randrange(1, 20)
					# Size the nodes for how often the word appears in the above dataset, if given.
					node["size"] = word_pair.get((word_type + "_occurrences"), 1)

					if highlight_words and word in highlight_words:
						node["color"] = "#19B0A3"
					else:
						node["color"] = None

					# Add that node
					date_network["nodes"].append(node)
					nodes_added.append(word)

			# Add edges, if not already added
			# Assume its undirectional, for now, so sort the words
			edge_label = "-".join(sorted([source_word,target_word]))

			if edge_label not in edges_added:

				# Edge attributes
				edge = {}
				edge["id"] = edge_label
				edge["source"] =  edge_label.split("-")[0]
				edge["target"] = edge_label.split("-")[1]
				edge["size"] = weight
				edge["label"] = edge_label # Unused by sigma but useful here
				edge["color"] = "#FFA5AC"
				# Add that edge
				date_network["edges"].append(edge)
				edges_added.append(edge_label)
				edge_id += 1

		# Add last network item to overall network object
		networks[current_date] = date_network

		return networks