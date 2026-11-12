"""
Generate network of wikipedia pages + categories in posts
"""
import re
import requests
from lxml import etree
from lxml.cssselect import CSSSelector as css
from io import StringIO
from urllib.parse import unquote
import networkx as nx

from backend.lib.processor import BasicProcessor
from common.lib.compatibility import Compatibility
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.helpers import urls_in_text, get_software_version

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters", "Sal Hagen"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class WikiURLCoLinker(BasicProcessor):
	"""
	Generate URL co-link network
	"""
	type = "wiki-category-network"  # job type ID
	category = "Networks"  # category
	title = "Wikipedia category network"  # title displayed in UI
	description = "Create a GEXF network file comprised network comprised of linked-to Wikipedia pages, linked to the categories they are part of. English Wikipedia only. Will only fetch the first 10,000 links."  # description displayed in UI
	extension = "gexf"  # extension of result file, used internally and in UI

	# Allow on top-level CSV/NDJSON datasets
	compatibility = Compatibility(top_dataset_only=True, extensions={"csv", "ndjson"})

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with all posts containing the original query exactly, ignoring any
		* or " in the query
		"""

		# links to English Wikipedia articles are the ones we are after, also
		# those to the mobile site; the address is not case-sensitive, the
		# page title after /wiki/ is
		wikipedia_link = re.compile(r"(?i:https?://en\.(m\.)?wikipedia\.org)/wiki/.")
		# wiki_page = re.compile(r"[\[\[[^\]]+\]\]")
		category_regex = re.compile(r"\[\[Category:[^\]]+\]\]")

		links = {}
		all_categories = {}
		errors = 0
		page_categories = {}
		processed = 0
		network = nx.Graph()

		self.dataset.update_status("Reading source file")

		for post in self.source_dataset.iterate_items(self):
			processed += 1
			if processed % 50 == 0:
				self.dataset.update_status("Extracting URLs from item %i" % processed)

			if not post["body"]:
				continue

			wiki_links = [link for link in urls_in_text(post["body"]) if wikipedia_link.match(link)]

			# if the result has an explicit url per post, take that into
			# account as well
			if "url" in post and post["url"]:
				wiki_links += [link for link in urls_in_text(post["url"]) if wikipedia_link.match(link)]

			# count each page once per post, however it is written
			for title in sorted({self.title_from_url(link) for link in wiki_links}):
				if not title:
					continue

				if title not in links:
					links[title] = 0

				links[title] += 1

			# Limit to the first 10,000 links extracted
			if len(links) >= 10000:
				break

		if not links:
			self.dataset.finish_as_empty("No links to English Wikipedia pages found")
			return

		self.dataset.log(f"Found links to {len(links):,} English Wikipedia pages")

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
		refused = ""

		# Wikipedia refuses requests that do not say which program sends them
		# and how to reach its makers
		user_agent = f"4cat/{get_software_version() or 'unknown'} (https://github.com/digitalmethodsinitiative/4cat)"

		self.dataset.update_status("Fetching categories from Wikipedia API...")
		for link in links:
			if link not in page_categories:
				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while fetching data from Wikipedia")

				page_categories[link] = set()
				self.dataset.update_status(
					"Fetching categories from Wikipedia API, page %i of %i" % (counter, len(links)))
				counter += 1

				# fetch wikipedia source; passing the title as a parameter makes
				# requests encode it, so that e.g. the & in "AT&T" is part of it
				try:
					page = requests.get("https://en.wikipedia.org/w/index.php", params={"title": link, "action": "edit"},
										headers={"User-Agent": user_agent}, timeout=30)
				except requests.RequestException as e:
					self.dataset.log(f"Could not reach Wikipedia for '{link}': {e}")
					errors += 1
					continue

				if page.status_code in (403, 429):
					# Wikipedia refuses to answer (403) or wants fewer requests
					# (429); it would refuse the other pages too, so stop asking
					reason = " ".join(re.sub(r"<[^>]*>", " ", page.text).split())[:200].rstrip(" .")
					refused = f"Wikipedia refused to answer (status {page.status_code}): {reason}"
					self.dataset.log(refused)
					del page_categories[link]
					break

				if page.status_code != 200:
					self.dataset.log(f"Wikipedia answered with status {page.status_code} for '{link}'")
					errors += 1
					continue

				# get link to image file from HTML returned
				parser = etree.HTMLParser()
				tree = etree.parse(StringIO(page.content.decode("utf-8")), parser)

				try:
					wiki_source = stringify_children(css("#wpTextbox1")(tree)[0])
				except IndexError:
					# for a page that does not exist, Wikipedia shows a
					# "permission error" instead of the page source
					self.dataset.log(f"Wikipedia did not show the source of '{link}'; the page may not exist")
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

		fetched = len(page_categories) - errors
		self.dataset.log(f"Got the categories of {fetched:,} of {len(links):,} pages")
		if not fetched:
			self.dataset.finish_with_error(
				f"{refused}. No network was made." if refused else
				f"Could not get the categories of any of the {len(links):,} Wikipedia pages; see the log for why"
			)
			return

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

		if refused:
			self.dataset.finish_with_warning(len(network.nodes), f"{refused}. The network only has the {fetched:,} "
																 f"pages fetched before that; see the log")
		elif errors:
			self.dataset.finish_with_warning(len(network.nodes), f"Network created, but the categories of {errors:,} "
																 f"of {len(links):,} pages could not be fetched; see "
																 f"the log for why")
		else:
			self.dataset.finish(len(network.nodes))

	@staticmethod
	def title_from_url(url):
		"""
		Get the title of the Wikipedia page a URL leads to

		In URLs, Wikipedia writes the spaces in a title as underscores, and
		characters such as & and + may be encoded. Titles always start with a
		capital letter. So "/wiki/AT%26T" and "/wiki/AT&T" both give "AT&T",
		and "/wiki/c%2B%2B" gives "C++".

		:param str url:  Link to a page on Wikipedia
		:return str:  The page title, or an empty string if the link has none
		"""
		title = url.split("/wiki/", 1)[-1]

		# Markdown, as in Reddit posts, writes a link's URL twice and puts a
		# backslash before each underscore in the visible copy, as in
		# "[.../wiki/Judah\_P._Benjamin](.../wiki/Judah_P._Benjamin)". Both
		# copies lead to one page, and a backslash cannot be part of a link to
		# a title anyway, as browsers read it as "/"
		title = title.replace("\\_", "_")

		# a link to a part of a page (#...) or with extra parameters (?...)
		# leads to the page itself
		title = re.split(r"[#?]", title, maxsplit=1)[0]

		title = unquote(title).replace("_", " ").strip()
		return title[:1].upper() + title[1:]
