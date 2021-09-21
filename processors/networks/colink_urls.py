"""
Generate co-link network of URLs in posts
"""
import re

from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput

import networkx as nx

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

class URLCoLinker(BasicProcessor):
	"""
	Generate URL co-link network
	"""
	type = "url-network"  # job type ID
	category = "Networks"  # category
	title = "URL co-link network"  # title displayed in UI
	description = "Create a Gephi-compatible GEXF network comprised of all URLs appearing in a post with at least " \
				  "one other URL. Appearing in the same post constitutes an edge between these nodes. Edges are " \
				  "weighted by amount of co-links."  # description displayed in UI
	extension = "gexf"  # extension of result file, used internally and in UI

	options = {
		"detail": {
			"type": UserInput.OPTION_CHOICE,
			"help": "Link detail level",
			"options": {
				"url": "Full URL",
				"domain": "Domain name"
			},
			"default": "url"
		},
		"level": {
			"type": UserInput.OPTION_CHOICE,
			"help": "Co-occurence context",
			"options": {
				"thread": "Thread (works best in full-thread data sets)",
				"post": "Post"
			},
			"default": "thread",
			"tooltip": "If 'thread' is selected, URLs are considered to occur together if they appear within the same "
					   "thread, even if they are in different posts."
		}
	}

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with all posts containing the original query exactly, ignoring any
		* or " in the query
		"""

		# we use these to extract URLs and host names if needed
		link_regex = re.compile(r"https?://[^\s\]()]+")
		www_regex = re.compile(r"^www\.")
		trailing_dot = re.compile(r"[.,)]$")

		self.dataset.update_status("Reading source file")

		links = {}
		processed = 0
		network = nx.Graph()

		for post in self.iterate_items(self.source_file):
			processed += 1
			if processed % 50 == 0:
				self.dataset.update_status("Extracting URLs from item %i" % processed)

			if not post["body"]:
				continue

			post_links = link_regex.findall(post["body"])

			# if the result has an explicit url per post, take that into
			# account as well
			if "url" in post and post["url"]:
				post_links.append(post["url"])

			if self.parameters.get("detail") == "domain":
				try:
					post_links = [www_regex.sub("", link.split("/")[2]) for link in post_links]
				except IndexError:
					# not a valid URL, e.g. "http://" without anything after the //
					pass

			# deduplicate, so repeated links within one posts don't inflate
			post_links = [trailing_dot.sub("", link) for link in post_links]
			# Encode the URLs, e.g. replace commas with '%2c', so it makes a nice gdf file
			post_links = [link.replace(",", "%2c").replace("'", "").replace('"',"").replace("\\_","_") for link in post_links]
			post_links = sorted(set(post_links))

			# if we're looking at a post level, each post gets its own
			# co-link set, but if we're doing this on a thread level, we
			# add all the links we found to one pool per thread, and then
			# create co-link pairs from that in the next for loop
			if self.parameters.get("level") == "post":
				unit_id = post["id"]
			else:
				unit_id = post["thread_id"]

			if unit_id not in links:
				links[unit_id] = []

			# in the case of post-level analysis, this is identical to just
			# post_links on its own
			links[unit_id] = [*post_links, *links[unit_id]]

		# create co-link pairs from all links per co-link unit (thread or post)
		self.dataset.update_status("Finding common URLs")
		for unit_id in links:
			post_links = links[unit_id]

			# ignore single links (which, of course, are not co-linked with
			# any other links)
			if len(post_links) <= 1:
				continue

			# create co-link pairs from link sets
			pairs = set()
			for from_link in post_links:
				# keep track of all URLs so we can easily write the node
				# list later
				if from_link not in network.nodes():
					network.add_node(from_link)

				for to_link in post_links:
					if to_link not in network.nodes():
						network.add_node(to_link)

					network.add_edge(from_link, to_link)

		self.dataset.update_status("Writing network file")
		nx.write_gexf(network, self.dataset.get_results_path())
		self.dataset.finish(len(network.nodes))
