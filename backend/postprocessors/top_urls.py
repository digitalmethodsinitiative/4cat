"""
Extract URLs from results
"""
import re

from csv import DictReader, DictWriter

from backend.abstract.postprocessor import BasicPostProcessor
from backend.lib.helpers import UserInput


class URLExtractor(BasicPostProcessor):
	"""
	Rank URLs by most mentioned
	"""
	type = "url-extractor"  # job type ID
	category = "Post metrics" # category
	title = "Top URLs"  # title displayed in UI
	description = "Extract URLs mentioned in the posts and sort them by most-mentioned. Note that archive and URL shortener links are not expanded."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	# the following determines the options available to the user via the 4CAT
	# interface.
	options = {
		"hostnames": {
			"type": UserInput.OPTION_TOGGLE,
			"default": True,
			"help": "Use hostnames (e.g. 'example.com') instead of full URL"
		}
	}

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column containing URLs and the other containing how often
		the URL was mentioned
		"""
		link_regex = re.compile(r"https?://[^\s]+")
		www_regex = re.compile(r"^www\.")
		links = {}

		self.query.update_status("Reading source file")
		with open(self.source_file, encoding='utf-8') as source:
			csv = DictReader(source)
			for post in csv:
				post_links = link_regex.findall(post["body"])
				if post_links:
					for link in post_links:
						# Extract domain name if user indicated so
						if self.parameters.get("hostnames", False):
							link = www_regex.sub("", link.split("/")[2])
						# Else just use the full URL
						if link not in links:
							links[link] = 0
						links[link] += 1

		results = [{"URL": link, "num_posts": links[link]} for link in links]
		results = sorted(results, key=lambda x: x["num_posts"], reverse=True)

		if not results:
			return

		self.query.write_csv_and_finish(results)