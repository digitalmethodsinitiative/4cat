"""
Import a CSV file as a new dataset
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/../..")
from backend.lib.database import Database
from backend.lib.logger import Logger
from backend.lib.dataset import DataSet

import csv
import time
import argparse
import shutil

from pathlib import Path

cli = argparse.ArgumentParser()
cli.add_argument("-i", "--input", required=True, help="csv to import")
args = cli.parse_args()

input = Path(args.input)
if not input.exists():
	print("File not found")
	sys.exit(1)

with open(input) as i:
	reader = csv.DictReader(i)
	rows = 0
	for row in reader:
		row += 1

required = ("id", "thread_id", "subject", "author", "timestamp", "body")
for field in required:
	if field not in reader.fieldnames:
		print("Column '%s' missing." % field)
		sys.exit(1)

logger = Logger()
new_set = DataSet(
	parameters={"user": "autologin", "filename": input.name, "time": int(time.time()), "datasource": "custom",
				"board": "upload"},
	db=Database(logger=logger))

shutil.copyfile(input, new_set.get_results_path())
new_set.finish(rows)