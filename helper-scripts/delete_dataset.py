"""
Delete a dataset
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/..")
from common.lib.database import Database
from common.lib.logger import Logger
from common.lib.dataset import DataSet

# parse parameters
cli = argparse.ArgumentParser(description="Deletes a dataset, the corresponding job, and any child datasets.")
cli.add_argument("-k", "--key", required=True, help="Dataset key to delete.")
cli.add_argument("-q", "--quiet", type=bool, default=False,
				 help="Whether to skip asking for confirmation. Defaults to false.")
args = cli.parse_args()

if not args.quiet:
	confirm = input("This will delete the dataset and any child datasets. Are you sure? (y/n)")
	if confirm.strip().lower() != "y":
		sys.exit(0)

logger = Logger()
database = Database(logger=logger, appname="delete-dataset")

# Initialize query
try:
	parent = DataSet(key=args.key, db=database)
except TypeError:
	print("No dataset found with that key.")
	sys.exit(1)


parent.delete()
print("Done. Note that running jobs for the datasets above are not stopped; you will have to wait for them to finish on their own.")
