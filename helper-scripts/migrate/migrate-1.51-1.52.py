# delete background jobs from queue
# these will be re-added on next restart with the new intervals
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

# Add new admin privilege to manage extensions
print("  Deleting background jobs from queue to be re-added on next restart...")
db.execute("DELETE FROM jobs WHERE jobtype IN ('datasource-metrics', 'clean-temp-files', 'check-for-updates')")

print("  Updating default value for llm.available_models setting...")
# this does not check the current value - it will be updated anyway by the
# refresh_items worker if an LLM server is configured
db.execute("UPDATE settings SET value = '{}' WHERE name = 'llm.available_models'")

print("  - done!")