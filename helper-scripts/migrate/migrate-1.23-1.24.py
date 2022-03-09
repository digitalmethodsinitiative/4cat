# Add 'is_deactivated' column to user table
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "'/../..")
from common.lib.database import Database
from common.lib.logger import Logger

import common.config_manager as config
log = Logger(output=True)
db = Database(logger=log, dbname=config.get('DB_NAME'), user=config.get('DB_USER'), password=config.get('DB_PASSWORD'), host=config.get('DB_HOST'), port=config.get('DB_PORT'), appname="4cat-migrate")

print("  Checking if users table has a column 'is_deactivated'...")
has_column = db.fetchone("SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'is_deactivated'")
if has_column["num"] == 0:
    print("  ...No, adding.")
    db.execute("ALTER TABLE users ADD COLUMN is_deactivated BOOLEAN DEFAULT False")
else:
    print("  ...Yes, nothing to update.")


print("  Done!")
