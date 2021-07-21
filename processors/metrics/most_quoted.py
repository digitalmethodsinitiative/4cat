"""
Example post-processor worker
"""
import csv
import re

from backend.abstract.processor import BasicProcessor

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)

class QuoteRanker(BasicProcessor):
	"""
	Rank posts by most-quoted
	"""
	type = "quote-ranker"  # job type ID
	category = "Post metrics" # category
	title = "Sort by most quoted"  # title displayed in UI
	description = "Sort posts by how often they were quoted by other posts in the data set. Post IDs may be correlated and triangulated with the full results set."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor on chan datasets

		:param module: Dataset or processor to determine compatibility with
		"""
		if module.is_dataset():
			return module.parameters.get("datasource") in ("4chan", "8chan", "8kun")
		return False


	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with an extra column containing the amount of times another post was
		quoted. The set is then sorted by that column.
		"""
		quoted = {}
		quoted_posts = {}
		fieldnames = []
		link = re.compile(r">>([0-9]+)")

		self.dataset.update_status("Reading source file")
		for post in self.iterate_items(self.source_file):
			quotes = re.findall(link, post["body"])
			if quotes:
				if quotes[0] not in quoted:
					quoted[quotes[0]] = 0
					quoted_posts[post["id"]] = post
					if not fieldnames:
						fieldnames = list(post.keys())

				quoted[quotes[0]] += 1

		if not quoted_posts :
			return

		most_quoted = sorted(quoted, key=lambda id: quoted[id], reverse=True)
		fieldnames.append("num_quoted")

		self.dataset.update_status("Writing results file")
		with self.dataset.get_results_path().open("w", encoding="utf-8") as results:
			writer = csv.DictWriter(results, fieldnames=fieldnames)
			writer.writeheader()

			for id in most_quoted:
				if id not in quoted_posts:
					continue
				post = quoted_posts[id]
				post["num_quoted"] = quoted[id]
				writer.writerow(post)

		self.dataset.update_status("Finished")
		self.dataset.finish(len(most_quoted))
