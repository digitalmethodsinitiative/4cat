"""
Queue queries for Emilija's Generals project
"""
import argparse
import sys
import csv
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/../..")
from backend.lib.database import Database
from backend.lib.logger import Logger
from backend.lib.queue import JobQueue
from backend.lib.dataset import DataSet

import config

logger = Logger()
database = Database(logger=logger, appname="delete-query")
queue = JobQueue(logger=logger, database=database)

with open("generals.csv") as input:
	reader = csv.DictReader(input, delimiter=";")
	for row in reader:
		print("Queueing %s" % row["label"])
		generals_query = row["4catified query"]
		query = DataSet(
			parameters={
				"board": "pol",
				"datasource": "4chan",
				"body_query": "",
				"subject_query": generals_query,
				"full_thread": True,
				"dense_threads": False,
				"dense_percentage": 15,
				"dense_length": 30,
				"country_flag": "all",
				"dense_country_percentage": 0,
				"random_amount": False,
				"min_date": 0,
				"max_date": 0,
				"user": "e.jokubauskaite@uva.nl",
				"next": [{
					"type": "thread-metadata",
					"parameters": {
						"copy_to": "/Users/stijn/PycharmProjects/4cat/results/generals/%s.csv" % row["label"].replace("/", "")
					}
				}]
			}, db=database)
		queue.add_job("4chan-search", remote_id=query.key)

print("Done.")
