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
    "version_match": "TEXT DEFAULT ''",
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

print("  Notifying 4CAT admin about new notification functionality")
db.insert("users_notifications", {
    "username": "!admin",
    "notification": "From this version onwards, 4CAT will fetch notifications concerning security warnings and upgrade "
                    "instructions from an external server.",
    "notification_long": "As of version 1.51, 4CAT will periodically contact the server at "
                         "[https://ping.4cat.nl](https://ping.4cat.nl) to check for news released by its developers, "
                         "e.g. to inform you about security issues or upgrade instructions.\n\n"
                         "You can read more about what happens with your personal data via the link above. In short: "
                         "no personally identifiable information (PII) is retained.\n\n"
                         "You can disable this functionality by going into the Control Panel's 'Settings' page, and "
                         "setting the 'Phone home URL' under '4CAT Tool Settings' to an empty value. 4CAT will still "
                         "let you know when a new version is available if you do this; but you will not receive any "
                         "other notifications, e.g. security warnings or upgrade instructions, so we recommend leaving "
                         "this enabled.",
    "allow_dismiss": True
}, safe=True)

# Add new admin privilege to manage extensions
print("  Ensuring new admin privilege to manage extensions exists...")
db.insert("settings", data={"name": "privileges.admin.can_manage_extensions", "value": "true", "tag": "admin"}, safe=True)

print("  - done!")