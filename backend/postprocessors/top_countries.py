"""
Determine which country code is the most prevalent in the data
"""
from csv import DictReader

from backend.abstract.postprocessor import BasicPostProcessor


class CountryCounter(BasicPostProcessor):
	"""
	Count countries

	Count how often each country code occurs in the result set
	"""
	type = "count-countries"  # job type ID
	category = "Post metrics" # category
	title = "Top countries"  # title displayed in UI
	description = "Generate a list of country codes present in the result set and sort it by how often the country is present."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with unique usernames and in the other one the amount
		of posts for that user name
		"""
		countries = {}

		self.query.update_status("Reading source file")
		with open(self.source_file, encoding="utf-8") as source:
			csv = DictReader(source)
			for post in csv:
				country = post["country_code"] if "country_code" in post else ""
				if country not in countries:
					countries[country] = 0
				countries[country] += 1

		results = [{"country": country, "num_posts": countries[country]} for country in countries]
		results = sorted(results, key=lambda x: x["num_posts"], reverse=True)

		if not results:
			return

		self.query.write_csv_and_finish(results)