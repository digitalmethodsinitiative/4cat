"""
Delete a snapshot through its unique timestamp
"""
import argparse
import glob
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/../..")
from backend.lib.database import Database
from backend.lib.logger import Logger
from backend.lib.queue import JobQueue
from backend.lib.query import DataSet

import config

# parse parameters
cli = argparse.ArgumentParser(description="Deletes a snapshot.")
cli.add_argument("-t", "--timestamp", required=True, help="Timestamp")
args = cli.parse_args()

try:
	timestamp = int(args.timestamp)
except TypeError:
	print("Invalid timestamp")
	sys.exit(1)

logger = Logger()
database = Database(logger=logger, appname="delete-query")
queue = JobQueue(logger=logger, database=database)

snapshots = database.fetchall("SELECT key FROM queries WHERE parameters::json->>'user' = 'daily-snapshot' AND (parameters::json->>'max_date')::int = %s", (timestamp,))
print("Deleting %i queries." % len(snapshots))
for snapshot in snapshots:
	query = DataSet(key=snapshot["key"], db=database)
	print("Deleting query %s and subqueries..." % query.key)
	query.delete()

if config.PATH_SNAPSHOTDATA and os.path.exists(config.PATH_SNAPSHOTDATA):
	print("Deleting snapshot data files.")
	os.chdir(config.PATH_SNAPSHOTDATA)
	files = glob.glob("%i-*" % timestamp)
	for file in files:
		print("Deleting %s." % file)
		os.unlink(file)
else:
	print("No valid snapshot data folder configured. Not deleting data files.")

print("Done.")