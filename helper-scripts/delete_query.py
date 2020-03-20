"""
Delete a query
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/..")
from backend.lib.database import Database
from backend.lib.logger import Logger
from backend.lib.dataset import DataSet

import config

# parse parameters
cli = argparse.ArgumentParser(description="Deletes a query, the corresponding job, and any sub-queries.")
cli.add_argument("-k", "--key", required=True, help="Query key to delete.")
cli.add_argument("-q", "--quiet", type=bool, default=False,
				 help="Whether to skip asking for confirmation. Defaults to false.")
args = cli.parse_args()

if not args.quiet:
	confirm = input("This will delete the query, and any sub-queries. Are you sure? (y/n)")
	if confirm.strip().lower() != "y":
		sys.exit(0)

logger = Logger()
database = Database(logger=logger, appname="delete-query")

# Initialize query
try:
	parent = DataSet(key=args.key, db=database)
except TypeError:
	print("No query found with that key.")
	sys.exit(1)


parent.delete()
print("Done. Note that running jobs for the queries above are not stopped; you will have to wait for them to finish on their own.")
