"""
Example post-processor worker
"""
from csv import DictReader

from backend.abstract.postprocessor import BasicPostProcessor


class UsernameExtractor(BasicPostProcessor):
	"""
	Example post-processor

	This is a very simple example post-processor.

	The four configuration options should be set for all post-processors. They
	contain information needed internally as well as information that is used
	to describe this post-processor with in a user interface.
	"""
	type = "extract-usernames"  # job type ID
	category = "Post metrics" # category
	title = "Top usernames"  # title displayed in UI
	description = "Build a list with distinct usernames in the source file, and how many posts were found per username"  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with unique usernames and in the other one the amount
		of posts for that user name
		"""
		users = {}

		self.query.update_status("Reading source file")
		with open(self.source_file, encoding='utf-8') as source:
			csv = DictReader(source)
			for post in csv:
				if post["author"] not in users:
					users[post["author"]] = 0
				users[post["author"]] += 1

		results = [{"username": username, "num_posts": users[username]} for username in users]
		results = sorted(results, key=lambda x: x["num_posts"], reverse=True)

		if not results:
			return

		self.query.write_csv_and_finish(results)