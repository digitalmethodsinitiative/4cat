# Ensure unique metrics index exists
import json
import sys
import os

from pathlib import Path

sys.path.insert(0, os.path.join(os.path.abspath(os.path.dirname(__file__)), "../.."))
from common.lib.database import Database
from common.lib.logger import Logger

log = Logger(output=True)

import configparser  # noqa: E402

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

print("  Checking if datasets table has a column 'software_source'...")
has_column = db.fetchone(
    "SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'datasets' AND column_name = 'software_source'"
)
if has_column["num"] == 0:
    print("  ...No, adding.")
    current_source = db.fetchone(
        "SELECT value FROM settings WHERE name = '4cat.github_url' AND tag = ''"
    )
    current_source = (
        json.loads(current_source["value"]) if current_source is not None else ""
    )
    db.execute(
        "ALTER TABLE datasets ADD COLUMN software_source TEXT DEFAULT %s",
        (current_source,),
    )
    db.commit()
else:
    print("  ...Yes, nothing to update.")
