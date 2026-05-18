import sys
import os

from pathlib import Path

sys.path.insert(0, os.path.join(os.path.abspath(os.path.dirname(__file__)), "../.."))
from common.lib.database import Database
from common.lib.logger import Logger

import configparser  # noqa: E402

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

# Add status_type column to datasets table
# This was done in 1.52-1.53 but database.sql lacked the column in that
# release, so new 1.53 installs could still lack the column because the script
# only runs on upgrade; this ensures 1.53 installs also have the column in all
# cases
print("  Checking for `status_type` column in datasets table...")
has_column = db.fetchone(
    "SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'datasets' AND column_name = 'status_type'"
)

if has_column["num"] > 0:
    print("    Datasets table already has column 'status_type'")
else:
    print("    Adding column 'status_type' to datasets table...")
    db.execute("ALTER TABLE datasets ADD status_type TEXT DEFAULT ''")

print("  - done!")
