# Drop unused column
import sys
import os

from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "'/../..")
from common.lib.database import Database
from common.lib.logger import Logger

log = Logger(output=True)

import configparser

ini = configparser.ConfigParser()
ini.read(Path(__file__).parent.parent.parent.resolve().joinpath("config/config.ini"))
db_config = ini["DATABASE"]

db = Database(logger=log, dbname=db_config["db_name"], user=db_config["db_user"], password=db_config["db_password"],
              host=db_config["db_host"], port=db_config["db_port"], appname="4cat-migrate")

print("  Dropping 'status' column from jobs table...")
status_column_check = db.fetchone(
    "SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'jobs' AND column_name = 'status'")
if status_column_check["num"] != 0:
    db.execute("ALTER TABLE jobs DROP COLUMN status")
    db.commit()
    print("  - dropped!")
else:
    print("  - already dropped, skipping!")