# Add 'is_deactivated' column to user table
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "'/../..")
from common.lib.database import Database
from common.lib.logger import Logger

import config

log = Logger(output=True)
db = Database(logger=log, dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD, host=config.DB_HOST,
              port=config.DB_PORT, appname="4cat-migrate")

print("  Checking if datasets table has a column 'is_private'...")
has_column = db.fetchone("SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'datasets' AND column_name = 'is_private'")
if has_column["num"] == 0:
    print("  ...No, adding.")
    db.execute("ALTER TABLE datasets ADD COLUMN is_private BOOLEAN DEFAULT TRUE")
    db.commit()

    # make existing datasets all non-private, as they were before
    db.execute("UPDATE datasets SET is_private = FALSE")
    db.commit()
else:
    print("  ...Yes, nothing to update.")

print("  Checking if datasets table has a column 'owner'...")
has_column = db.fetchone("SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'datasets' AND column_name = 'owner'")
if has_column["num"] == 0:
    print("  ...No, adding.")
    db.execute("ALTER TABLE datasets ADD COLUMN owner VARCHAR DEFAULT 'anonymous'")
    db.commit()

    # make existing datasets all non-private, as they were before
    db.execute("UPDATE datasets SET owner = parameters::json->>'user' WHERE parameters::json->>'user' IS NOT NULL")
    db.commit()
else:
    print("  ...Yes, nothing to update.")


print("  Done!")