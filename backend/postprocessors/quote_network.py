"""
Extract most-used images from corpus
"""
import re

from csv import DictReader

from backend.lib.postprocessor import BasicPostProcessor


class QuoteNetworkGrapher(BasicPostProcessor):
	"""
	Quote network graph

	Creates a network of posts quoting each other
	"""
	type = "quote-network"  # job type ID
	title = "Quote network"  # title displayed in UI
	description = "Create a Gephi-compatible network of quoted posts, with each reference to another post creating an edge between those posts. Post IDs may be correlated and triangulated with the full results set."  # description displayed in UI
	extension = "gdf"  # extension of result file, used internally and in UI

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with image hashes, one with the first file name used
		for the image, and one with the amount of times the image was used
		"""
		nodes = []
		edges = []
		gdf = ""
		link = re.compile(r">>([0-9]+)")

		self.query.update_status("Reading source file")
		with open(self.source_file) as source:
			csv = DictReader(source)
			for post in csv:
				quotes = re.findall(link, post["body"])
				if quotes:
					if post["id"] not in nodes:
						nodes.append(post["id"])

					if quotes[0] not in nodes:
						nodes.append(quotes[0])

					edges.append([post["id"], quotes[0]])

		self.query.update_status("Writing results file")
		with open(self.query.get_results_path(), "w") as results:
			results.write("nodedef>name VARCHAR,label VARCHAR\n")
			for node in nodes:
				results.write("post-" + node + ',"' + node + '"\n')

			results.write("edgedef>node1 VARCHAR, node2 VARCHAR\n")
			for edge in edges:
				results.write("post-" + edge[0] + ",post-" + edge[1] + "\n")

		self.query.update_status("Finished")
		self.query.finish(len(edges))