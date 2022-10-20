"""
Generate network of wikipedia pages + categories in posts
"""
import re
import requests

from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput
from lxml import etree
from lxml.cssselect import CSSSelector as css
from io import StringIO

import networkx as nx

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters", "Sal Hagen"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

class URLCoLinker(BasicProcessor):
	"""
	Generate URL co-link network
	"""
	type = "wiki-category-network"  # job type ID
	category = "Networks"  # category
	title = "Wikipedia category network"  # title displayed in UI
	description = "Create a GEXF network file comprised network comprised of linked-to Wikipedia pages, linked to the categories they are part of. English Wikipedia only. Will only fetch the first 10,000 links."  # description displayed in UI
	extension = "gexf"  # extension of result file, used internally and in UI

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with all posts containing the original query exactly, ignoring any
		* or " in the query
		"""

		# we use these to extract URLs and host names if needed
		link_regex = re.compile(r"https?://en.wikipedia\.org/wiki/[^\s.]+")
		wiki_page = re.compile(r"[\[\[[^\]]+\]\]")
		category_regex = re.compile(r"\[\[Category:[^\]]+\]\]")
		trailing_comma = re.compile(r",$")

		links = {}
		all_categories = {}
		errors = 0
		page_categories = {}
		page_links = {}
		deep_pages = {}
		processed = 0
		network = nx.Graph()

		self.dataset.update_status("Reading source file")

		for post in self.source_dataset.iterate_items(self):
			processed += 1
			if processed % 50 == 0:
				self.dataset.update_status("Extracting URLs from item %i" % processed)

			if not post["body"]:
				continue
				
			wiki_links = link_regex.findall(post["body"])

			# if the result has an explicit url per post, take that into
			# account as well
			if "url" in post and post["url"] and link_regex.match(post["url"]):
				wiki_links.append(link_regex.findall(post["url"]))

			wiki_links = [trailing_comma.sub("", link) for link in wiki_links]

			# Encode the URLs, e.g. replace commas with '%2c', so it makes a nice gdf file
			wiki_links = [link.replace(",", "%2c").replace("'", "").replace('"',"").replace("\\_","_") for link in wiki_links]
			wiki_links = sorted(set(wiki_links))

			for link in wiki_links:
				link = "/wiki/".join(link.split("/wiki/")[1:]).split("#")[0]
				if link not in links:
					links[link] = 0

				links[link] += 1

			# Limit to the first 10,000 links extracted
			if len(links) >= 10000:
				break

		# just a helper function to get the HTML content of a node
		def stringify_children(node):
			from lxml.etree import tostring
			from itertools import chain
			parts = ([node.text] +
					 list(chain(*([c.text, tostring(c), c.tail] for c in node.getchildren()))) +
					 [node.tail])
			# filter removes possible Nones in texts and tails
			return ''.join(filter(None, parts))

		counter = 0

		self.dataset.update_status("Fetching categories from Wikipedia API...")
		for link in links:
			if link not in page_categories:
				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while fetching data from Wikipedia")

				page_categories[link] = set()
				self.dataset.update_status(
					"Fetching categories from Wikipedia API, page %i of %i" % (counter, len(links)))
				counter += 1

				# fetch wikipedia source
				url = "https://en.wikipedia.org/w/index.php?title=" + link + "&action=edit"
				try:
					page = requests.get(url)
				except requests.RequestException:
					errors += 1
					continue

				if page.status_code != 200:
					errors += 1
					continue

				# get link to image file from HTML returned
				parser = etree.HTMLParser()
				tree = etree.parse(StringIO(page.content.decode("utf-8")), parser)

				try:
					wiki_source = stringify_children(css("#wpTextbox1")(tree)[0])
				except IndexError:
					# not a source page?
					errors += 1
					continue

				# extract category names from category link syntax
				categories = category_regex.findall(wiki_source)
				categories = set([":".join(category.split(":")[1:])[:-2].split("|")[0] for category in categories])

				# save category links
				for category in categories:

					# Add " (cat)" to the category strings.
					# This is needed because pages can sometimes have the same name as the category.
					# This will result in a faulty graph, since there's duplicate nodes.
					
					category += " (cat)"

					if category not in all_categories:
						all_categories[category] = 0

					all_categories[category] += 1
					page_categories[link].add(category)

		# write GEXF file
		ids = {}
		id_no = 0
		for page in page_categories:
			network.add_node(id_no, label=page.replace("_", " "), **({"weight": links[page], "type": "page"}))
			ids[page.replace("_", " ")] = id_no
			id_no += 1

		for category in all_categories:
			network.add_node(id_no, label=category.replace("_", " "), **({"weight": all_categories[category], "type": "category"}))
			ids[category.replace("_", " ")] = id_no
			id_no += 1

		for page in page_categories:
			for category in page_categories[page]:
				network.add_edge(ids[page.replace("_", " ")], ids[category.replace("_", " ")], **({"weight": all_categories[category]}))

		self.dataset.update_status("Writing network file")
		nx.write_gexf(network, self.dataset.get_results_path())
		self.dataset.finish(len(network.nodes))
