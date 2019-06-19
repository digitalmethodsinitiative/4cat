"""
Queue a snapshot for a given timestamp
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/../..")
from backend.lib.database import Database
from backend.lib.logger import Logger
from backend.lib.queue import JobQueue
from backend.lib.dataset import DataSet

import config

# parse parameters
cli = argparse.ArgumentParser(description="Deletes a query, the corresponding job, and any sub-queries.")
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

snapshots = database.fetchall("SELECT key FROM queries WHERE timestamp = %s AND parameters::json->>'user' = 'daily-snapshot'", (timestamp,))
for snapshot in snapshots:
	query = DataSet(key=snapshot["key"], db=database)
	query.delete()
	print("Deleting query %s..." % query.key)

queue.add_job("schedule-snapshot", details={"epoch":timestamp}, remote_id="snapshot-%i" % timestamp)
print("Queued.")