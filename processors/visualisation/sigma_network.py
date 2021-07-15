"""
Create a network of word relations.

The corresponding JavaScript file is found in webtool/static/js.
The corresponding CSS file is found in webtool/static/css.  

"""
import json
import unicodedata
import random

import config

from common.lib.helpers import UserInput
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

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor on network files

		:param module: Dataset or processor to determine compatibility with
		"""
		if module.is_dataset():
			return module.get_results_path().suffix == ".gdf"
		else:
			return module.extension == "gdf"

	def process(self):
		"""
		Create a HTML file with a network derived from a source_dataset dataset.

		"""
		# Get json data to use in the graph.
		# gdf and non-network files need to be parsed first.

		self.dataset.update_status("Generating graph data")

		# If collocations, make sure n_size is 2 (bigrams)
		if self.source_dataset.data["type"] == "collocations":

			parent_parameters = json.loads(self.source_dataset.data["parameters"])

			if int(parent_parameters["n_size"]) != 2:
				self.dataset.update_status("Co-word networks can only be generated for bigrams (n_size: 2)")
				self.dataset.finish(-1)
				return

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

		try:
			html_file = self.get_html_page(data)
		except MemoryError:
			self.dataset.update_status("Out of memory while processing network. Try downloading and visualising locally instead.", is_final=True)
			self.dataset.finish(0)
			return

		# Write HTML file
		with self.dataset.get_results_path().open("w", encoding="utf-8") as output_file:
			output_file.write(html_file)

		# Finish
		self.dataset.update_status("Finished")
		self.dataset.finish(1)

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

		highlight_nodes = self.parameters.get("highlight")
		if highlight_nodes:
			highlight_nodes = [highlight_node for highlight_node in str(highlight_nodes).split(",")]

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
					node = {"size": 1}

					# If everything is ok, there's no commas in gdf file's node info,
					# so split on a comma and loop through the items

					node_items = line.split(",")
					for i, node_item in enumerate(node_items):

						# Do some string cleaning
						node_item = self.sanitise(node_item)
						label = node_item
						if len(label) > 30:
							label = label[:27] + "..."

						# Mandatory nodes
						# Use the "name" info to write mandatory data
						if node_types[i].startswith("name "):
							node["id"] = node_item
							node["label"] = label
							node["x"] = random.randrange(1, 20)
							node["y"] = random.randrange(1, 20)
							if highlight_nodes and node_item in highlight_nodes:
								node["color"] = "#19B0A3"

						elif node_types[i].startswith("label "):
							node["label"] = label

						elif node_types[i].startswith("weight "):
							node["size"] = float(node_item)

						# A new, custom node attribute (e.g. "category")
						else:
							if node_types[i].endswith("INTEGER"): # Parse to int if it's indicated
								node_item = int(node_item)
							node[node_types[i].split(" ")[0]] = node_item
					
					network["nodes"].append(node)

				# Loop through edges
				else:
					
					edge = {"size": 1}

					# If everything was parsed ok, there's no commas in gdf file's node info,
					# so split on a comma and loop through the items
					edge_items = line.split(",")

					for i, edge_item in enumerate(edge_items):

						# Do some string cleaning
						edge_item = self.sanitise(edge_item)

						# Loop through the types of nodes we've encountered before
						# Ambiguous edges
						if edge_types[i].startswith("node1 ") or edge_types[i].startswith("from ") or edge_types[i].startswith("source "):
							edge["source"] = edge_item
							edges_added.append(edge_item)
						elif edge_types[i].startswith("node2 ") or edge_types[i].startswith("to ") or edge_types[i].startswith("target "):
							edge["target"] = edge_item

						# Tag -> user edges
						elif edge_types[i].startswith("tag "):
							edge["source"] = edge_item
						elif edge_types[i].startswith("user "):
							edge["target"] = edge_item

						# Tag -> user edges
						elif edge_types[i].startswith("name "):
							edge["source"] = edge_item
						elif edge_types[i].startswith("category "):
							edge["target"] = edge_item

						elif edge_types[i].startswith("weight "):
							edge["size"] = float(edge_item)
						else:
							# A new, custom edge attribute (e.g. "category")
							if edge_types[i].endswith("INTEGER"): # Parse to int if it's indicated
								edge_item = int(edge_item)
							edge[edge_types[i].split(" ")[0]] = edge_item # Store the item under first word, like 'category VARCHAR'
					
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
		if self.source_dataset.data["type"] == "word-embeddings-neighbours":
			source_column = "source_word"
			target_column = "nearest_neighbour"
			weight_column = "cosine_similarity"

		elif self.source_dataset.data["type"] == "collocations":
			source_column = "word_1"
			target_column = "word_2"
			weight_column = "value"

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
		highlight_nodes = self.parameters.get("highlight")
		if highlight_nodes:
			highlight_nodes = [highlight_node for highlight_node in str(highlight_nodes).split(",")]

		# Go through the source csv
		for row in self.iterate_items(self.source_file):
			
			# Check if this is a new date, and if so, add it as a new list
			if row["date"] != current_date:
 
				# Add the existing network if it exists (i.e. if we're processing a "current_date")
				if current_date and date_network:
					networks[current_date] = date_network
				
				# Empty the dict for the next round
				date_network = {"nodes": [], "edges": []}
				nodes_added = []
				edges_added = []

				current_date = row["date"]

			# Set the source and target nodes
			source_node = row[source_column]
			target_node = row[target_column]

			# Use this to loop through both words
			source_and_target = [source_node, target_node]

			# Used for edge weights
			weight = row.get(weight_column)
			if weight:
				weight = float(weight)
				if weight < 0: # Increase edge size for < 0 numbers
					weight = 1
				weight = float(weight)
			if not weight:
				weight = 1

			# Add nodes, if not already added
			for i, node_item in enumerate(source_and_target):

				node_type = "source" # Used for indexing the right column node size
				if i == 1:
					node_type = "target"

				if node_item not in nodes_added:

					label = node_item
					if len(label) > 30:
						label = label[:27] + "..."
					
					# Node attributes
					node = {}
					node["id"] = node_item # We're using the node_item as an ID here
					node["label"] = label
					node["x"] = random.randrange(1, 20)
					node["y"] = random.randrange(1, 20)

					# Size the nodes for how often the node_item appears in the above dataset, if given.
					node["size"] = row.get((node_type + "_occurrences"), 1)

					if highlight_nodes and node_item in highlight_nodes:
						node["color"] = "#19B0A3"
					
					# Add that node
					date_network["nodes"].append(node)
					nodes_added.append(node_item)

			# Add edges, if not already added
			# Assume its undirectional, for now, so sort the words
			edge_label = "-".join(sorted([source_node, target_node]))

			if edge_label not in edges_added:

				# Edge attributes
				edge = {}
				edge["id"] = edge_label
				edge["source"] =  edge_label.split("-")[0]
				edge["target"] = edge_label.split("-")[1]
				edge["size"] = weight
				edge["label"] = edge_label # Unused by sigma but adding just in case
				
				# Add that edge
				date_network["edges"].append(edge)
				edges_added.append(edge_label)
				edge_id += 1

		# Add last network item to overall network object
		networks[current_date] = date_network

		return networks

	def sanitise(self, string):
		"""
		Sanitises string labels
		"""

		string = string.strip()
		if string.endswith("\n"):
			string = string[:-2]
		if string.startswith("'") or string.startswith("\""):
			string = string[1:]
		if string.endswith("'") or string.endswith("\""):
			string = string[:-1]

		# Happens sometimes
		string = string.replace("\\\\","") # Not ideal for now, but it works
		string = string.replace("'","’")

		# This normalises special characters to one form
		# e.g. variable width characters in Japanese signs
		string = unicodedata.normalize("NFC", string)

		return string

	def get_html_page(self, data):
		"""
		Returns a html string with which a sigma graph can be displayed and manipulated.
		"""

		html_string = """
		<!DOCTYPE html>
		<html>
		<head>

			<title>Sigma js network</title>
			<meta content="text/html;charset=utf-8" http-equiv="Content-Type">
			<meta content="utf-8" http-equiv="encoding">

			<link rel="stylesheet" type="text/css" href="**server**/static/css/sigma_network.css">

			<!-- Font Awesome -->
		 <link href="**server**/static/fontawesome/css/fontawesome.css" rel="stylesheet">
		 <link href="**server**/static/fontawesome/css/regular.css" rel="stylesheet">
		 <link href="**server**/static/fontawesome/css/solid.css" rel="stylesheet">
		 <link href="**server**/static/fontawesome/css/brands.css" rel="stylesheet">

			<!-- START SIGMA IMPORTS -->
			<script src="https://code.jquery.com/jquery-3.4.1.min.js" integrity="sha256-CSXorXvZcTkaix6Yvo6HppcZGetbYMGWSFlBw8HfCJo=" crossorigin="anonymous"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/sigma.core.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/conrad.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/utils/sigma.utils.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/utils/sigma.polyfills.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/sigma.settings.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/classes/sigma.classes.dispatcher.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/classes/sigma.classes.configurable.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/classes/sigma.classes.graph.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/classes/sigma.classes.camera.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/classes/sigma.classes.quad.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/classes/sigma.classes.edgequad.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/captors/sigma.captors.mouse.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/captors/sigma.captors.touch.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/sigma.renderers.canvas.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/sigma.renderers.webgl.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/sigma.renderers.svg.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/sigma.renderers.def.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/webgl/sigma.webgl.nodes.def.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/webgl/sigma.webgl.nodes.fast.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/webgl/sigma.webgl.edges.def.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/webgl/sigma.webgl.edges.fast.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/webgl/sigma.webgl.edges.arrow.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/canvas/sigma.canvas.labels.def.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/canvas/sigma.canvas.hovers.def.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/canvas/sigma.canvas.nodes.def.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/canvas/sigma.canvas.edges.def.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/canvas/sigma.canvas.edges.curve.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/canvas/sigma.canvas.edges.arrow.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/canvas/sigma.canvas.edges.curvedArrow.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/canvas/sigma.canvas.edgehovers.def.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/canvas/sigma.canvas.edgehovers.curve.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/canvas/sigma.canvas.edgehovers.arrow.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/canvas/sigma.canvas.edgehovers.curvedArrow.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/canvas/sigma.canvas.extremities.def.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/svg/sigma.svg.utils.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/svg/sigma.svg.nodes.def.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/svg/sigma.svg.edges.def.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/svg/sigma.svg.edges.curve.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/svg/sigma.svg.labels.def.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/renderers/svg/sigma.svg.hovers.def.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/middlewares/sigma.middlewares.rescale.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/middlewares/sigma.middlewares.copy.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/misc/sigma.misc.animation.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/misc/sigma.misc.bindEvents.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/misc/sigma.misc.bindDOMEvents.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/src/misc/sigma.misc.drawHovers.js"></script>

			<script src="**server**/static/js/sigma.js-1.2.1/plugins/sigma.layout.forceAtlas2/worker.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/plugins/sigma.layout.forceAtlas2/supervisor.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/plugins/sigma.exporters.svg/sigma.exporters.svg.js"></script>
			<script src="**server**/static/js/sigma.js-1.2.1/plugins/sigma.plugins.filter/sigma.plugins.filter.js"></script>

			<!-- END SIGMA IMPORTS -->

		</head>

		<body>

			<!-- Control panel -->
			<div id='control-panel'>

				<div id="network-name-box" class="control-panel-notice">
					Undefined network
				</div>
				

				<div id="main-alert-box" class="alert-box control-panel-notice"></div>

				<!-- slider for manipulating networks -->
				<div id="slider-container">
					<div class="control-panel-notice">
					Slide to change date.
						<div>
							<input id="time-slider" type="range" min="1" max="100" value="1">
						</div>
						<div>
							<button id="btn-animate-slider"><i  class="fa fa-spin fa-sync-alt invisible" ></i> <span class="button-text">Start animation</span></button>
						</div>
					</div>
				</div>
				<hr>

				<div id="parameter-alert-box" class="alert-box"></div>

				<div id="graph-manipulation">

					<!-- Settings ForceAtlas2 / gravity -->
					<div class="graph-manipulation-box" id="network-settings">
						<h2 class="graph-manipulation-box-header">Network settings</h2>
						<p>See the <a href="https://github.com/jacomyal/sigma.js/tree/master/plugins/sigma.layout.forceAtlas2" target="__blank">sigma js documentation</a> for parameter explanations.</p>

						<!-- Start / stop ForceAtlas2 -->
						<div class="graph-manipulation-subbox" id="start-force-container">
							<button id="start-force" class="standalone-button">
								<i id="hourglass" class='fa fa-spin fa-sync-alt invisible'></i> 
								<span class="button-text">Start ForceAtlas2</span>
							</button>
						</div>
						<!-- Other network settings -->
						<div class="graph-manipulation-subbox">
							<p><label for="gravity">Gravity: </label>
								<input class="parameter-input" id="gravity" name="gravity" type="number" min="1" value="1">
							</p>
							<p><label for="strong-gravity">Strong gravity: </label>
								<input class="parameter-input" id="strong-gravity" name="strong-gravity" type="checkbox">
							</p>
							<p><label for="edge-weight-influence">Edge weight influence: </label>
								<input class="parameter-input" id="edge-weight-influence" name="edge-weight-influence" type="number" min="0" value="0">
							</p>
							<p><label for="scaling-ratio">Scaling ratio: </label>
								<input class="parameter-input" id="scaling-ratio" name="scaling-ratio" type="number" min="1" value="1">
							</p>
						</div>
						<div class="graph-manipulation-subbox">
							<p><label for="linlog-mode">LinLog mode: </label>
								<input class="parameter-input" id="linlog-mode" name="linlog-mode" type="checkbox">
							</p>
						</div>
						<div class="graph-manipulation-subbox">
							<p><label for="outbound-attraction-distribution">Outbound Attraction Distribution: </label>
								<input class="parameter-input" id="outbound-attraction-distribution" name="outbound-attraction-distribution" type="checkbox">
							</p>
						</div>
						<div class="graph-manipulation-subbox">
							<p><label for="adjust-sizes">Adjust sizes: </label>
								<input class="parameter-input"id="adjust-sizes" name="adjust-sizes" type="checkbox"  value="">
							</p>
						</div>
						<div class="graph-manipulation-subbox">
							<p><label for="barnes-hut-optimise">Barnes-Hut optimise: </label>
								<input class="parameter-input" id="barnes-hut-optimise" name="barnes-hut-optimise" type="checkbox" checked>
							</p>
							<p><label for="barnes-hut-theta">Barnes-Hut theta: </label>
								<input class="parameter-input" id="barnes-hut-theta" name="barnes-hut-theta" type="number" min="0" value="0.5">
							</p>
						</div>
						<div class="graph-manipulation-subbox">
							<p><label for="slow-down">Slow down: </label>
								<input class="parameter-input" id="slow-down" name="slow-down" type="number" value="1">
							</p>
						</div>
						<div class="graph-manipulation-subbox">
							<p><label for="min-degree">Minimum degree: </label>
								<input class="parameter-input" id="min-degree" name="min-degree" type="number" value="1">
							</p>
						</div>

					</div>
					<hr>

					<!-- Visual settings -->
					<div class="graph-manipulation-box" id="visual-settings"></div>
						<h2 class="graph-manipulation-box-header">Visual</h2>
						<h3 class="graph-manipulation-box-header">Labels</h3>
						<div class="graph-manipulation-subbox">
							<p><label for="show-labels">Show labels: </label>
								<input class="parameter-input" id="show-labels" name="show-labels" type="checkbox" checked>
							</p>
							<p><label for="label-size">Label size: </label>
								<input class="parameter-input" id="label-size" name="label-size" type="number" min="1" value="18">
							</p>
							<p><label for="label-size-type">Size labels by node size: </label>
								<input class="parameter-input" id="label-size-type" name="label-size-type" type="checkbox" checked>
							</p>
							<p><label for="label-threshold">Label threshold: </label>
								<input class="parameter-input" id="label-threshold" name="label-threshold" type="number" min="0.1" value="1">
							</p>
							<p><label for="label-colour">Label colour: </label>
								<input class="parameter-input" id="label-colour" name="label-colour" type="color" value="#00000">
							</p>
						</div>
						<h3 class="graph-manipulation-box-header">Nodes and edges</h3>
						<div class="graph-manipulation-subbox">
							<p><label for="min-node-size">Min node size: </label>
								<input class="parameter-input" id="min-node-size" name="min-node-size" type="number" min="0.1" value="1">
							</p>
							<p><label for="max-node-size">Max node size: </label>
								<input class="parameter-input" id="max-node-size" name="max-node-size" type="number" min="0.1" value="2">
							</p>
						</div>
						<div class="graph-manipulation-subbox">
							<p><label for="min-edge-size">Min edge size: </label>
								<input class="parameter-input" id="min-edge-size" name="min-edge-size" type="number" min="0.1" value="0.1">
							</p>
							<p><label for="max-edge-size">Max edge size: </label>
								<input class="parameter-input" id="max-edge-size" name="max-edge-size" type="number" min="0.1" value="1">
							</p>
						</div>
						<div class="graph-manipulation-subbox">
							<p><label for="node-colour">Node colour: </label>
								<input class="parameter-input" id="node-colour" name="node-colour" type="color" value="#CE1B28">
							</p>
							<p><label for="edge-colour">Edge colour: </label>
								<input class="parameter-input" id="edge-colour" name="edge-colour" type="color" value="#FFA5AC">
							</p>
						</div>
					</div>
					<hr>
					<div class="graph-manipulation-box" id="visual-settings">
						<h2 class="graph-manipulation-box-header">Save to svg</h2>
						<p>
							<input class="parameter-input full-width" id="file-name" name="file-name" type="text" placeholder="sigma-graph.svg">
						</p>
						<button id="save-svg" class="standalone-button">
							<span class="button-text">Download</span>
						</button>
					</div>
				</div>

			</div>

			<div id="footer">
				<p>Made with <a href='https://archive.4plebs.org' target='_blank'>4CAT</a> and <a href="https://github.com/jacomyal/sigma.js">sigma js</a>.</p>
			</div>

			<!-- Where the network graph will be -->
			<div id="graph-container">
			</div>

			<!-- Load up some more JavaScripts -->
			<script src="**server**/static/js/sigma_network.js" charset="utf-8"></script>
			<script type="text/javascript">

				// Initialise the graph
				json_str = '**json_str**'
				console.log(json_str)
				var core_json = JSON.parse(json_str);
				console.log(core_json);
				init_network(core_json);

			</script>

		</body>
		</html>
		"""

		server_url = "https" if config.FlaskConfig.SERVER_HTTPS else "http"
		server_url += "://%s" % config.FlaskConfig.SERVER_NAME

		# JSONify and make sure any encoding errors are replaced (happens with large files).
		json_str = json.dumps(data).replace("\\\\","") # Not ideal for now, but it works.

		# Let's try and catch as much encoding issues as we can
		try:
			json.loads(json_str)
		
		except json.decoder.JSONDecodeError as e:
			p = int(str(e).split("(char ")[-1].replace(")",""))
			invalid_str = json_str[p-10:p+10]
			self.dataset.update_status("Invalid JSON - encountered %s" % str(invalid_str))
			raise Exception(e)

		# Split if the string is very long,
		# else it will throw JavaScript errors.
		max_len = 100000

		# This occurs sometimes with URLs
		json_str = json_str.replace("<script>", "").replace("</script>","")

		if len(json_str) > max_len:
			self.dataset.update_status("Splitting JSON string into chunks")
			split_json_str = ""
			prev_i = 0

			for i in range(len(json_str)):

				if i > 0 and i % max_len == 0:

					# Make sure we're splitting on a whitespace.
					# Splitting on a unicode character will give errors.
					split_i = i
					while True:
						if json_str[split_i] == " ":
							break
						else:
							split_i -= 1

					json_slice = json_str[prev_i:split_i]

					split_json_str += json_slice + "'+\n'"
					prev_i = split_i

			# Also add at the very end
			json_slice = json_str[prev_i:len(json_str)]
			split_json_str += json_slice

			json_str = split_json_str

		return html_string.replace("**server**", server_url).replace("**json_str**", json_str)