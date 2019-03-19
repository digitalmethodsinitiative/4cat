"""
Delete a query
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/../..")
from backend.lib.database import Database
from backend.lib.logger import Logger
from backend.lib.queue import JobQueue
from backend.lib.job import Job, JobNotFoundException
from backend.lib.query import DataSet

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
database = Database(logger=logger)

# Initialize query
try:
	parent = DataSet(key=args.key, db=database)
except TypeError:
	print("No query found with that key.")
	sys.exit(1)

# Find subqueries/analyses/postprocessors
keys = [row["key"] for row in database.fetchall("SELECT key FROM queries WHERE key_parent = %s", (parent.key,))]
keys.append(parent.key)

# Delete all of them
for key in keys:
	try:
		query = DataSet(key=key, db=database)
	except TypeError as e:
		print("Could not initialize query %s (%s), skipping." % (key, e))
		continue

	# If a job is queued for the query, delete it too
	if "job" in query.parameters:
		try:
			job = Job.get_by_ID(query.parameters["job"], database)
			print("Finishing job %s..." % job.data["id"])
			job.finish()
		except JobNotFoundException:
			pass

	# If there is a result file already, delete it
	path = query.get_results_path()
	if os.path.isfile(path):
		print("Deleting %s..." % path)
		os.unlink(path)

	# Finally, delete it from the database
	print("Deleting query %s from database..." % query.key)
	database.delete("queries", where={"key": query.key})

print(
	"Done. Note that running jobs for the queries above are not stopped; you will have to wait for them to finish on their own.")
