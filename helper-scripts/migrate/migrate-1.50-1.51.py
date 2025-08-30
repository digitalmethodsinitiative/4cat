# Add a column to the notifications table where a long(er) version of the
# notification can be viewed
import sys
import os

from pathlib import Path

sys.path.insert(0, os.path.join(os.path.abspath(os.path.dirname(__file__)), "../.."))
from common.lib.database import Database
from common.lib.logger import Logger

import configparser

log = Logger(output=True)
ini = configparser.ConfigParser()
ini.read(Path(__file__).parent.parent.parent.resolve().joinpath("config/config.ini"))
db_config = ini["DATABASE"]

db = Database(
    logger=log,
    dbname=db_config["db_name"],
    user=db_config["db_user"],
    password=db_config["db_password"],
    host=db_config["db_host"],
    port=db_config["db_port"],
    appname="4cat-migrate",
)

columns = {
    "notification_long": "TEXT DEFAULT ''",
    "canonical_id": "TEXT DEFAULT ''",
    "is_dismissed": "BOOLEAN DEFAULT FALSE",
}

for column, definition in columns.items():
    print(f"  Checking for `{column}` column in notifications table...")
    has_column = db.fetchone(
        "SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'users_notifications' AND column_name = %s",
        (column,),
    )

    if has_column["num"] > 0:
        print(f"    Notifications table already has column '{column}'")
    else:
        print(f"    Adding column '{column}' to notifications table...")
        db.execute("ALTER TABLE users_notifications ADD " + column + " " + definition)

print("  Re-making unique index for notifications table...")
db.execute("DROP INDEX IF EXISTS users_notifications_unique")
db.execute(
    "CREATE UNIQUE INDEX IF NOT EXISTS users_notifications_unique ON users_notifications (canonical_id, username, notification)"
)

print("  - done!")
