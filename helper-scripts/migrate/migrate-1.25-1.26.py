# Add 'instance' column to jobs table
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "'/../..")
from common.lib.database import Database
from common.lib.logger import Logger

import config

log = Logger(output=True)
db = Database(logger=log, dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD, host=config.DB_HOST,
              port=config.DB_PORT, appname="4cat-migrate")

print("  Checking if jobs table has a column 'instance'...")
has_column = db.fetchone("SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'jobs' AND column_name = 'instance'")
if has_column["num"] == 0:
    print("  ...No, adding.")
    db.execute("ALTER TABLE jobs ADD COLUMN instance VARCHAR DEFAULT '*'")
else:
    print("  ...Yes, nothing to update.")

print("  Dropping 'unique job' index if it exists...")
db.execute("DROP INDEX IF EXISTS unique_job")

print("  Creating anew...")
db.execute("CREATE UNIQUE INDEX IF NOT EXISTS unique_job ON jobs (jobtype, remote_id, instance)")
print("  ...done")

print("  Dropping job status column if it exists...")
has_column = db.fetchone("SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'jobs' AND column_name = 'status'")
if has_column["num"] == 0:
    print("  ...found column, dropping")
    db.execute("ALTER TABLE jobs DROP COLUMN status")
else:
    print("  ...column already dropped or never created")

print("  Done!")
