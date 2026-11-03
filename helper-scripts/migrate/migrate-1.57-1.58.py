# Model entries in `llm.available_models` gained a `supported_tasks` field, so
# that processors can tell generative models and embedding models apart.
#
# Clearing the inventory forces it to be rebuilt.
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

print("  Clearing known LLM models so they are re-indexed with task support...")
has_setting = db.fetchone("SELECT COUNT(*) AS num FROM settings WHERE name = 'llm.available_models'")

if has_setting["num"] > 0:
    db.upsert("settings", {"name": "llm.available_models", "value": "{}", "tag": ""}, constraints=["name", "tag"])
    print("    ...cleared; models will be re-indexed on 4CAT restart")
else:
    print("    ...no models indexed yet, nothing to do")

print("  - done!")
