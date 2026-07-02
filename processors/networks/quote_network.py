"""
Extract most-used images from corpus
"""
import re

from backend.lib.processor import BasicProcessor, ProcessorDescription
from common.lib.compatibility import Compatibility
from common.lib.outputs import Network

import networkx as nx

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

class QuoteNetworkGrapher(BasicProcessor):
	"""
	Quote network graph

	Creates a network of posts quoting each other
	"""
	type = "quote-network"  # job type ID
	description = ProcessorDescription(
		title="Reply network",
		category="Networks",
		tags=["network"],
		description="Create a GEXF network file of posts replying to each other. Each reference to another post creates an edge between the two posts.",
		icon="circle-nodes",
	)
	extension = "gexf"  # extension of result file, used internally and in UI
	# a graph file, no column table
	output = Network()

	# chan datasets (posts reply to / quote each other)
	compatibility = Compatibility(datasources={"fourchan", "eightchan", "eightkun"})

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with image hashes, one with the first file name used
		for the image, and one with the amount of times the image was used
		"""
		link = re.compile(r">>([0-9]+)")

		network = nx.Graph()

		self.dataset.update_status("Reading source file")
		for post in self.source_dataset.iterate_items(self):
			quotes = link.findall(post["body"])
			if quotes:
				if post["id"] not in network.nodes:
					network.add_node(post["id"])

				if quotes[0] not in network.nodes:
					network.add_node(quotes[0])

				network.add_edge(post["id"], quotes[0])

		self.dataset.update_status("Writing network file")
		nx.write_gexf(network, self.dataset.get_results_path())
		self.dataset.finish(len(network.nodes))