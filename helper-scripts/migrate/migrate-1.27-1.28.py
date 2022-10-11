# Add notifications tables and indexes
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "'/../..")
from common.lib.database import Database
from common.lib.logger import Logger

log = Logger(output=True)
import common.config_manager as config
db = Database(logger=log, dbname=config.get('DB_NAME'), user=config.get('DB_USER'), password=config.get('DB_PASSWORD'), host=config.get('DB_HOST'), port=config.get('DB_PORT'), appname="4cat-migrate")

print("  Checking if 'users_notifications' table exists...")
table = db.fetchone("SELECT EXISTS ( SELECT FROM information_schema.tables WHERE table_schema = %s AND table_name = %s )", ("public", "users_notifications"))

if not table["exists"]:
    print("  ...No, adding.")
    db.execute("""
        CREATE TABLE IF NOT EXISTS users_notifications (
        id                  SERIAL PRIMARY KEY,
        username            TEXT,
        notification        TEXT,
        timestamp_expires   INTEGER,
        allow_dismiss       BOOLEAN DEFAULT TRUE);
    """)

    db.execute("""
        CREATE INDEX IF NOT EXISTS users_notifications_name
          ON users_notifications (
            username
          );
    """)

    db.execute("""
        CREATE INDEX IF NOT EXISTS users_notifications_name
          ON users_notifications (
            username
          );
    """)

    db.commit()
else:
    print("  ...Yes, nothing to update.")

print("  Done!")
