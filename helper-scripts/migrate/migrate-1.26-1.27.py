# Add 'is_deactivated' column to user table
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "'/../..")
from common.lib.database import Database
from common.lib.logger import Logger

log = Logger(output=True)
import common.config_manager as config
db = Database(logger=log, dbname=config.get('DB_NAME'), user=config.get('DB_USER'), password=config.get('DB_PASSWORD'), host=config.get('DB_HOST'), port=config.get('DB_PORT'), appname="4cat-migrate")

print("  Checking if datasets table has a column 'progress'...")
has_column = db.fetchone("SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'datasets' AND column_name = 'progress'")
if has_column["num"] == 0:
    print("  ...No, adding.")
    db.execute("ALTER TABLE datasets ADD COLUMN progress FLOAT DEFAULT 0.0")
    db.commit()

    # make existing datasets all non-private, as they were before
    db.execute("UPDATE datasets SET progress = 1 WHERE is_finished = TRUE")
    db.commit()
else:
    print("  ...Yes, nothing to update.")

print("  Done!")
