"""
Exact match filter
"""
from csv import DictReader, DictWriter

from backend.lib.postprocessor import BasicPostProcessor
from backend.lib.query import SearchQuery

class ExactMatcher(BasicPostProcessor):
	"""
	Extract exact matches

	Filters result set so only exact matches are left
	"""
	type = "match-exactly"  # job type ID
	title = "Exact matches"  # title displayed in UI
	description = "Filter results so only posts containing the exact input query are left. Posts are matched against the full query text (search operators are interpreted as plain text, * and \" characters are ignored)"  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with all posts containing the original query exactly, ignoring any
		* or " in the query
		"""
		posts = []
		parent = SearchQuery(key=self.query.parameters["parent"], db=self.db)
		match = parent.parameters["body_query"].replace('"', "").replace("*", "")

		self.query.update_status("Reading source file")
		with open(self.source_file) as source:
			csv = DictReader(source)
			for post in csv:
				if match in post["body"]:
					posts.append(post)

		self.query.write_csv_and_finish(posts)