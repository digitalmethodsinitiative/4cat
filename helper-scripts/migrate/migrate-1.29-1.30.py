# For imageboard data sources,
# create an index on the basis of a thread's archived or deleted timestamps.
# This is used to quickly fetch the last few threads if they haven't been marked
# as inactive (i.e. archived or deleted). We need these to check the status of these
# threads after they've disappeared off the index.

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "'/../..")
from common.lib.database import Database
from common.lib.logger import Logger

log = Logger(output=True)
import common.config_manager as config
db = Database(logger=log, dbname=config.get('DB_NAME'), user=config.get('DB_USER'), password=config.get('DB_PASSWORD'), host=config.get('DB_HOST'), port=config.get('DB_PORT'), appname="4cat-migrate")

print("  Creating new indexes for enabled imageboard datasources...")

imageboards_enabled = False

# Check for 8kun
is_8kun = db.fetchone("SELECT EXISTS ( SELECT FROM information_schema.tables WHERE table_name = %s )" % "'threads_8kun'")
if is_8kun["exists"]:
    
    imageboards_enabled = True

    print("  Creating 'threads_archiving_8kun' index if it didn't exist already...")
    
    db.execute("""
        CREATE INDEX IF NOT EXISTS threads_archiving_8kun
          ON threads_8kun (
            timestamp_deleted, timestamp_archived, timestamp_modified, board
          );
    """)

    db.commit()

# Check for 4chan
is_4chan = db.fetchone("SELECT EXISTS ( SELECT FROM information_schema.tables WHERE table_name = %s )" % "'threads_4chan'")
if is_4chan["exists"]:

    imageboards_enabled = True

    print("  Creating 'threads_archiving_4chan' index if it didn't exist already...")
    db.execute("""
        CREATE INDEX IF NOT EXISTS threads_archiving_4chan
          ON threads_4chan (
            timestamp_deleted, timestamp_archived, timestamp_modified, board
          );
    """)

    db.commit()

if not imageboards_enabled:
    print("  No imageboard data sources enabled")
else:
    print("  Done!")
