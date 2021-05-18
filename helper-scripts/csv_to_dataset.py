"""
Import a CSV file as a new dataset
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/..")
from common.lib.database import Database
from common.lib.logger import Logger
from common.lib.dataset import DataSet

import csv
import time
import argparse
import shutil

from pathlib import Path

cli = argparse.ArgumentParser()
cli.add_argument("-i", "--input", required=True, help="csv to import")
cli.add_argument("-u", "--user", default="autologin", help="Username to assign the dataset to")
cli.add_argument("-d", "--datasource", default="custom", help="Datasource to assign to dataset")
args = cli.parse_args()

input = Path(args.input)
if not input.exists():
	print("File not found")
	sys.exit(1)

with open(input) as i:
	reader = csv.DictReader(i)
	rows = 0
	for row in reader:
		rows += 1

required = ("id", "thread_id", "subject", "author", "timestamp", "body")
for field in required:
	if field not in reader.fieldnames:
		print("Column '%s' missing." % field)
		sys.exit(1)

logger = Logger()
new_set = DataSet(
	parameters={"user": args.user, "filename": input.name, "time": int(time.time()), "datasource": args.datasource,
				"board": "upload"}, type="%s-search" % args.datasource,
	db=Database(logger=logger))

shutil.copyfile(input, new_set.get_results_path())
new_set.finish(rows)