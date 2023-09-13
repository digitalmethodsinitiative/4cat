# Add notifications tables and indexes
import configparser
import sys
import os

from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "'/../..")
from common.lib.database import Database
from common.lib.logger import Logger

log = Logger(output=True)

ini = configparser.ConfigParser()
ini.read(Path(__file__).parent.parent.parent.resolve().joinpath("config/config.ini"))
db_config = ini["DATABASE"]

db = Database(logger=log, dbname=db_config["db_name"], user=db_config["db_user"], password=db_config["db_password"],
              host=db_config["db_host"], port=db_config["db_port"], appname="4cat-migrate")

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
