"""
Collapse post bodies into one long string
"""
import re
from csv import DictReader

from backend.abstract.postprocessor import BasicPostProcessor


class Stringify(BasicPostProcessor):
	"""
	Merge post body into one long string
	"""
	type = "stringify-posts"  # job type ID
	category = "Text analysis" # category
	title = "Collapse into string"  # title displayed in UI
	description = "Collapses all posts in the results into one plain text string. The result can be used for word clouds, word trees, et cetera."  # description displayed in UI
	extension = "txt"  # extension of result file, used internally and in UI

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a plain text file
		containing all post bodies as one continuous string, sanitized.
		"""
		delete_regex = re.compile(r"[^a-zA-Z)(.,\n -]")

		posts = 0
		self.query.update_status("Processing posts")
		with open(self.query.get_results_path(), "w") as results:
			with open(self.source_file, encoding='utf-8') as source:
				csv = DictReader(source)
				for post in csv:
					posts += 1
					results.write(re.sub(r"\s+", " ", delete_regex.sub(" ", post["body"])).strip() + " ")


		self.query.update_status("Finished")
		self.query.finish(posts)