import csv
import datetime
from csv import DictReader, DictWriter


def generate_json(file):
	"""
	Generates a JSON structure usable for Raphael.js to make a RankFlow
	
	"""

	result = {"max": 0, "buckets":[],
        "authors": {}
        }

	with open(file , encoding="utf-8") as source:
		csv = DictReader(source)

		# names = set([post["collocation"] for post in csv])
		# for i, name in enumerate(names):
		# 	result["authors"][str(i)] = {"name": name}
		# csv = DictReader(source)

		authors = []
		timestamps = []

		for post in csv:
			print(post)

			# Set author names
			if post["collocation"] not in authors:
				authors.append(post["collocation"])
				author_key = str(len(result["authors"]))
				result["authors"][author_key] = {}
				result["authors"][author_key]["n"] = post["collocation"]
			else:
				author_key = authors.index(post["collocation"])

			timestamp = int(datetime.datetime.strptime(post["date"], "%Y-%m").timestamp())
			print(timestamp)
			if timestamp not in timestamps:
				result["buckets"].append({"d":timestamp, "i": [[author_key, int(post["value"]) * 10]]})
				timestamps.append(timestamp)
				print(timestamps)
			else:
				result["buckets"][len(result["buckets"]) - 1]["i"].append([author_key, int(post["value"]) * 10])

			# Set max value
			if int(post["value"]) > result["max"]:
				result["max"] = int(post["value"])

	print(result)
if __name__ == '__main__':
	generate_json('collocations.csv')
