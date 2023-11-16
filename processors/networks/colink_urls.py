"""
Generate co-link network of URLs in posts
"""
import re
import time

import psutil

from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException
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
	title = "URL co-occurence network"  # title displayed in UI
	description = "Create a GEXF network file comprised of URLs appearing together (in a post or thread). " \
				  "Edges are weighted by amount of co-links."  # description displayed in UI
	extension = "gexf"  # extension of result file, used internally and in UI

	options = {
		"detail": {
			"type": UserInput.OPTION_CHOICE,
			"help": "Use URL or domain name",
			"options": {
				"url": "Full URL",
				"domain": "Domain name"
			},
			"default": "url"
		},
		"level": {
			"type": UserInput.OPTION_CHOICE,
			"help": "Set co-occurence by",
			"options": {
				"thread": "Thread (works best in full-thread datasets)",
				"post": "Post"
			},
			"default": "thread",
			"tooltip": "If 'thread' is selected, URLs are considered to co-occur if they appear within the same "
					   "thread, even if they are in different posts."
		}
	}

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with all posts containing the original query exactly, ignoring any
		* or " in the query
		"""
		start_time = time.time()
		# we use these to extract URLs and host names if needed
		link_regex = re.compile(r"https?://[^\s\]()]+")
		www_regex = re.compile(r"^www\.")
		trailing_dot = re.compile(r"[.,)]$")

		self.dataset.update_status("Reading source file")
		update_on_item = max(10, int(self.source_dataset.num_rows / 100))

		links = {}
		processed = 0
		# create an undirected network
		network = nx.Graph()

		for post in self.source_dataset.iterate_items(self):
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while collecting links")

			processed += 1
			if processed % update_on_item == 0:
				self.dataset.update_status("Extracting URLs from item %i" % processed)
				self.dataset.update_progress(processed / (self.source_dataset.num_rows * 2))

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
		# # This is faster than the below for loop, but apparently uses more memory (crashing on giant datasets where the for loop does not), plus we're only talking about seconds per million edges
		# [network.add_edge(from_link, to_link) for post_links in links.values() if len(post_links) > 1 for i, from_link in enumerate(post_links) for to_link in post_links[i + 1:]]

		update_on_item = max(int(len(links) / 100), 1)
		for i, post_links in enumerate(links.values()):
			if i % update_on_item == 0:
				self.dataset.update_status("Collecting URL links from item %i" % i)
				self.dataset.update_progress((self.source_dataset.num_rows + i) / (self.source_dataset.num_rows * 2))

			# ignore single links (which, of course, are not co-linked with
			# any other links)
			if len(post_links) <= 1:
				continue

			while post_links:
				from_link = post_links.pop()

				for to_link in post_links:
					if self.interrupted:
						raise ProcessorInterruptedException("Interrupted while creating network edges")

					network.add_edge(from_link, to_link)

		self.dataset.update_status(f"Network has {len(network.nodes)} and {len(network.edges)} edges")
		self.dataset.log(f"time elapsed: {time.time() - start_time:.2f} seconds")
		self.dataset.update_status("Writing network file")
		if psutil.virtual_memory().percent > 95:
			self.dataset.update_status("WARNING: memory usage about 95%; network may fail...")
			self.log.warning(f"Memory usage above 95%: network dataset {self.dataset.key}")
			#TODO: add perhaps kill the processor? It's frustrating that we can collect the data but not write it!
		nx.write_gexf(network, self.dataset.get_results_path())
		self.dataset.log(f"time to complete: {time.time() - start_time:.2f} seconds")
		self.dataset.finish(len(network.nodes))

