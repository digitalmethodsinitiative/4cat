# Update the 'annotations' table so every annotation has its own row.
# also add extra data
import sys
import os
import json

from pathlib import Path

sys.path.insert(0, os.path.join(os.path.abspath(os.path.dirname(__file__)), "../.."))
from common.lib.database import Database
from common.lib.logger import Logger

log = Logger(output=True)

import configparser

ini = configparser.ConfigParser()
ini.read(Path(__file__).parent.parent.parent.resolve().joinpath("config/config.ini"))
db_config = ini["DATABASE"]

db = Database(logger=log, dbname=db_config["db_name"], user=db_config["db_user"], password=db_config["db_password"],
              host=db_config["db_host"], port=db_config["db_port"], appname="4cat-migrate")

print("  Adding `from_dataset` column to annotations table...")
# Original annotations table had columns 'key' and 'annotations', new annotations has 'dataset' among others
has_column = db.fetchone("SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'annotations' AND column_name = 'from_dataset'")

# Ensure we do not attempt to update the annotations table if it has already been updated
# This will drop the annotations table and create a new one losing all annotations
# (both backend and frontend run migrate.py in case they have to update different aspects)
if has_column["num"] > 0:
    print("    Annotations table seems to have been updated already")
else:
    print("    Annotations table needs to be updated")
    db.execute("ALTER TABLE annotations ADD from_dataset TEXT")


print("    Creating indexes for `from_dataset` and unique fields for the annotations table...")
db.execute("""
CREATE INDEX IF NOT EXISTS annotations_from_dataset
ON annotations (
    from_dataset
);
DROP INDEX IF EXISTS annotation_unique;
CREATE UNIQUE INDEX annotation_unique
ON annotations (
    dataset,
    item_id,
    field_id
);
""")

print("  - done!")