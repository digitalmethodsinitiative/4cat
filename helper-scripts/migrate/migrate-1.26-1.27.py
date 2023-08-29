# Add 'is_deactivated' column to user table
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

print("  Checking if datasets table has a column 'progress'...")
has_column = db.fetchone("SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'datasets' AND column_name = 'progress'")
if has_column["num"] == 0:
    print("  ...No, adding.")
    db.execute("ALTER TABLE datasets ADD COLUMN progress FLOAT DEFAULT 0.0")
    db.commit()

    # make existing datasets all non-private, as they were before
    db.execute("UPDATE datasets SET progress = 1 WHERE is_finished = TRUE")
    db.commit()
else:
    print("  ...Yes, nothing to update.")

print("  Done!")
