"""
Delete all snapshot queries
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/../..")
from backend.lib.database import Database
from backend.lib.logger import Logger
from backend.lib.dataset import DataSet

logger = Logger()
database = Database(logger=logger, appname="snapshot-deleter")

snapshots = database.fetchall("SELECT key FROM queries WHERE parameters::json->>'user' = 'daily-snapshot'")

for snapshot in snapshots:
	print("Deleting %s" % snapshot["key"])
	query = DataSet(key=snapshot["key"], db=database)
	query.delete()