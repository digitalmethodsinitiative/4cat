"""
Create a network of word relations.

The corresponding JavaScript file is found in webtool/static/js.
The corresponding CSS file is found in webtool/static/css.  

"""
import json
import random
import re

import config

from pathlib import Path

from backend.lib.helpers import UserInput
from backend.abstract.processor import BasicProcessor

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

class SigmaNetwork(BasicProcessor):
	"""
	Generate a html page with a sigma js graph.
	"""

	type = "sigma-network"  # job type ID
	category = "Visualisation"  # category
	title = "Sigma js network"  # title displayed in UI
	description = "Visualise a network in the browser with sigma js."  # description displayed in UI
	extension = "html"  # extension of result file, used internally and in UI
	accepts = ["word-embeddings-neighbours", "url-network", "cotag-network", "quote-network", "wiki-category-network"]  # query types this post-processor accepts as input
	preview_allowed = False # Will slow down the page too much

	input = "csv"
	output = "html"

	options = {
		"highlight": {
			"type": UserInput.OPTION_TEXT,
			"default": "",
			"options": {
				"highlight": ""
			},
			"help": "Highlight these nodes in the network"
		}
	}

	def process(self):
		"""
		Create a HTML file with a network derived from a parent dataset.

		"""
		# Get json data to use in the graph.
		# gdf and non-network files need to be parsed first.

		self.dataset.update_status("Generating graph data")

		if str(self.source_file).endswith(".csv"):
			data = self.generate_json_from_csv(self.source_file)
		elif str(self.source_file).endswith(".gdf"):
			data = self.generate_json_from_gdf(self.source_file)
		else:
			self.dataset.update_status("Invalid source file")
			self.dataset.finish(-1)
			return

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

		# Generate a html file based on the retrieved json data
		with open(config.PATH_ROOT + "/processors/visualisation/sigma_network.html") as template:
			output = template.read().replace("**json**", json.dumps(data)).replace("**server**", server_url)

		# Write HTML file
		with self.dataset.get_results_path().open("w", encoding="utf-8") as output_file:
			output_file.write(output)

		# Finish
		self.dataset.update_status("Finished")
		self.dataset.finish(len(output))

	def generate_json_from_gdf(self, source_file):
		""" 
		Generates a sigma.js compatible JSON object from a gdf file.
		This can only be one graph.

		:param source_file, str: The source file of the dataset.

		"""

		# Result file, we'll be appending data to this
		network = {"nodes": [], "edges": []}

		nodes_added = []
		edges_added = []

		# Used to know wheter the lines we're reading refers to nodes or edges
		looping_through_nodes = True

		highlight_words = self.parameters.get("highlight")
		if highlight_words:
			highlight_words = [highlight_word for highlight_word in str(highlight_words).split(",")]

		with source_file.open(encoding="utf-8") as source:

			# Get the amount of nodes and their info from the first line in the file
			first_line = source.readline()
			node_types = [node.strip() for node in first_line.replace("nodedef>", "").split(",")]

			for line in source.readlines():

				if not line:
					continue
				
				# This line indicates the start of edge information
				if line.startswith("edgedef>"):
					looping_through_nodes = False
					edge_types = [edge.strip() for edge in line.replace("edgedef>", "").split(",")]
					continue

				if looping_through_nodes:

					# Save the node info here
					node = {}

					# If everything is ok, there's no commas in gdf file's node info,
					# so split on a comma and loop through the items
					node_items = line.split(",")

					for i, node_item in enumerate(node_items):

						# Do some string cleaning
						node_item = node_item.strip()
						if node_item.startswith("'"):
							node_item = node_item[1:]
						if node_item.endswith("'"):
							node_item = node_item[:-1]
						if node_item.endswith("\n"):
							node_item = node_item[:-2]

						# Mandatory nodes
						if node_types[i].startswith("name "):
							node["id"] = str(node_item)
							nodes_added.append(node_item)
							node["label"] = str(node_item)
							node["x"] = random.randrange(1, 20)
							node["y"] = random.randrange(1, 20)
							if highlight_words and node_item in highlight_words:
								node["color"] = "#19B0A3"

						elif node_types[i].startswith("weight "):
							node["size"] = float(node_item)

						# A new, custom node type (e.g. "category")
						else:
							if node_types[i].endswith("INTEGER"): # Parse to int if it's indicated
								node_item = int(node_item)
							node[node_types[i]] = node_item
					
					network["nodes"].append(node)

				# Loop through edges
				else:
					
					edge = {"size": 1}

					# If everything is ok, there's no commas in gdf file's node info,
					# so split on a comma and loop through the items
					edge_items = line.split(",")

					for i, edge_item in enumerate(edge_items):

						# Do some string cleaning
						edge_item = edge_item.strip()
						if edge_item.startswith("'"):
							edge_item = edge_item[1:]
						if edge_item.endswith("'"):
							edge_item = edge_item[:-1]
						if edge_item.endswith("\n"):
							edge_item = edge_item[:-2]

						# Loop through the types of nodes we've encountered before
						if edge_types[i].startswith("node1 "):
							edge["source"] = str(edge_item)
							edges_added.append(edge_item)
						elif edge_types[i].startswith("node2 "):
							edge["target"] = str(edge_item)

						elif edge_types[i].startswith("weight "):
							edge["size"] = float(edge_item)
						else:
							# A new, custom node type (e.g. "category")
							if edge_types[i].endswith("INTEGER"): # Parse to int if it's indicated
								edge_item = int(edge_item)
							edge[edge_types[i]] = edge_item
					
					edge["id"] = "-".join(sorted([edge["source"], edge["target"]]))
					edge["label"] = "-".join(sorted([edge["source"], edge["target"]]))
					
					network["edges"].append(edge)

		return {"network": network}


	def generate_json_from_csv(self, source_file):
		"""
		Generates a sigma.js compatible JSON object from a csv file.
		This may allow multiple networks in one json, each bound to a specific dictionary key.
		This allows selecting varying date-networks.

		:param source_file, str: The source file of the dataset.

		"""

		# Set the right column names
		if self.parent.data["type"] == "word-embeddings-neighbours":
			source_column = "source_word"
			target_column = "nearest_neighbour"
			weight_column = "cosine_similarity"

		elif self.parent.data["type"] == "collocations": # To do!
			source_column = "word1"
			target_column = "word2"
			weight_column = "weight"

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
			source_word = word_pair[source_column]
			target_word = word_pair[target_column]

			# Use this to loop through both words
			source_and_target = [source_word, target_word]

			# Used for edge weights
			weight = word_pair.get(weight_column)
			if weight:
				weight = float(weight)
				if weight < 1: # Increase edge size for < numbers
					weight = weight * 10
				weight = float(weight)
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
				edge["size"] = weight * 10
				edge["label"] = edge_label # Unused by sigma but useful here
				
				# Add that edge
				date_network["edges"].append(edge)
				edges_added.append(edge_label)
				edge_id += 1

		# Add last network item to overall network object
		networks[current_date] = date_network

		return networks