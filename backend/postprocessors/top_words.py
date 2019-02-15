"""
Determine which country code is the most prevalent in the data
"""
import re

from stop_words import get_stop_words
from csv import DictReader

from backend.abstract.postprocessor import BasicPostProcessor


class PostTokeniser(BasicPostProcessor):
	"""
	Count countries

	Count how often each country code occurs in the result set
	"""
	type = "count-words"  # job type ID

	category = "Text analysis" # category
	title = "Top (popular) words"  # title displayed in UI
	description = "Generate a list of most-used words used in the results, and how often they are used. Stop words are ignored."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with unique usernames and in the other one the amount
		of posts for that user name
		"""
		tokens = {}
		delete_regex = re.compile(r"[^a-zA-Z0-9 ]")
		stopwords = get_stop_words("en")

		self.query.update_status("Reading source file")
		with open(self.source_file, encoding='utf-8') as source:
			csv = DictReader(source)
			for post in csv:
				body = re.sub("\s+", " ", delete_regex.sub("", post["body"])).lower()
				post_tokens = body.split(" ")
				for token in post_tokens:
					if token == "" or token in stopwords:
						continue

					if token not in tokens:
						tokens[token] = 0
					tokens[token] += 1

		results = [{"word": token, "num_posts": tokens[token]} for token in tokens if tokens[token] > 1]
		results = sorted(results, key=lambda x: x["num_posts"], reverse=True)

		if not results:
			return

		self.query.write_csv_and_finish(results)