"""
Generate co-link network of URLs in posts
"""
import csv
import re

from backend.abstract.processor import BasicProcessor
from backend.lib.helpers import UserInput


class URLCoLinker(BasicProcessor):
	"""
	Generate URL co-link network
	"""
	type = "url-network"  # job type ID
	category = "Networks"  # category
	title = "URL co-link network"  # title displayed in UI
	description = "Create a Gephi-compatible network comprised of all URLs appearing in a post with at least one other " \
				  "URL. Appearing in the same post constitutes an edge between these nodes. Edges are weighted by amount " \
				  "of co-links."  # description displayed in UI
	extension = "gdf"  # extension of result file, used internally and in UI

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
			"default": "thread"
		}
	}

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with all posts containing the original query exactly, ignoring any
		* or " in the query
		"""
		months = {}

		# we use these to extract URLs and host names if needed
		link_regex = re.compile(r"https?://[^\s)]+")
		www_regex = re.compile(r"^www\.")
		trailing_dot = re.compile(r"[.,)]$")

		self.dataset.update_status("Reading source file")

		colink = {}
		urls = set()
		links = {}
		with self.source_file.open() as input:
			reader = csv.DictReader(input)
			for post in reader:
				post_links = link_regex.findall(post["body"])

				# if the result has an explicit url per post, take that into
				# account as well
				if "url" in post and post["url"]:
					post_links.append(post["url"])

				if self.parameters.get("detail", self.options["detail"]["default"]) == "domain":
					post_links = [www_regex.sub("", link.split("/")[2]) for link in post_links]

				# deduplicate, so repeated links within one posts don't inflate
				post_links = [trailing_dot.sub("", link) for link in post_links]
				post_links = sorted(set(post_links))

				# if we're looking at a post level, each post gets its own
				# co-link set, but if we're doing this on a thread level, we
				# add all the links we found to one pool per thread, and then
				# create co-link pairs from that in the next for loop
				if self.parameters.get("level", self.options["level"]["default"]) == "post":
					unit_id = post["id"]
				else:
					unit_id = post["thread_id"]

				if unit_id not in links:
					links[unit_id] = []

				# in the case of post-level analysis, this is identical to just
				# post_links on its own
				links[unit_id] = [*post_links, *links[unit_id]]

			# create co-link pairs from all links per co-link unit (thread or post)
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
					urls.add(from_link)

					for to_link in post_links:
						if to_link == from_link:
							continue

						# "to" and "from" are actually meaningless here, so by
						# sorting here we only include each pair of URLs in one
						# version only
						pair = sorted([from_link, to_link])
						pairs.add(" ".join(pair))

				# determine weight of edge by how often co-link occurs
				for pair in pairs:
					if pair not in colink:
						colink[pair] = 0
					colink[pair] += 1

		# write GDF file
		with self.dataset.get_results_path().open("w", encoding="utf-8") as results:
			results.write("nodedef>name VARCHAR\n")
			for url in urls:
				results.write("'" + url + "'\n")

			results.write("edgedef>node1 VARCHAR, node2 VARCHAR, weight INTEGER\n")
			for pair in colink:
				results.write(
					"'" + pair.split(" ")[0] +"','" + pair.split(" ")[1] + "'," + str(
						colink[pair]) + "\n")

		self.dataset.finish(len(colink))
