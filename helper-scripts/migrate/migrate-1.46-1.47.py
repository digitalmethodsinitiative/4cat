# Add finished_at column to datasets table
import json
import sys
import os
import datetime

from pathlib import Path

sys.path.insert(0, os.path.join(os.path.abspath(os.path.dirname(__file__)), "../.."))
from common.lib.database import Database
from common.lib.logger import Logger
from common.lib.dataset import DataSet
from common.lib.helpers import get_last_line

log = Logger(output=True)

import configparser

ini = configparser.ConfigParser()
ini.read(Path(__file__).parent.parent.parent.resolve().joinpath("config/config.ini"))
db_config = ini["DATABASE"]

db = Database(logger=log, dbname=db_config["db_name"], user=db_config["db_user"], password=db_config["db_password"],
              host=db_config["db_host"], port=db_config["db_port"], appname="4cat-migrate")

print("  Checking if datasets table has a column 'finished_at'...")
has_column = db.fetchone(
    "SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'datasets' AND column_name = 'finished_at'")
if has_column["num"] == 0:
    print("  ...No, adding.")
    db.execute("ALTER TABLE datasets ADD COLUMN finished_at INTEGER DEFAULT NULL")
    print("  ...Added column. Updating datasets with information based on logs.")
    dataset_ids = db.fetchall("SELECT key FROM datasets WHERE is_finished = TRUE")
    unable_to_update = []
    update_data = []

    for dataset in dataset_ids:
        key = dataset["key"]
        dataset = DataSet(key=key, db=db)

        if dataset.get_log_path().exists():
            try:
                finished_at = datetime.datetime.strptime(get_last_line(dataset.get_log_path())[:24], "%c")
                update_data.append((key, int(finished_at.timestamp())))
            except ValueError as e:
                # Unable to parse datetime from last line
                print(f" ...Unable to parse datetime from last line for dataset {key}: {e}")
                unable_to_update.append(key)
        else:
            # No log file; unable to determine finished_at
            print(f" ...Unable to determine finished_at for dataset {key}; no log file.")
            unable_to_update.append(key)

    if update_data:
        db.execute_many("UPDATE datasets SET finished_at = data.finished_at FROM (VALUES %s) AS data (key, finished_at) WHERE datasets.key = data.key", replacements=update_data)

    db.commit()
    print(f"  ...Updated {len(update_data)} datasets.")
    if len(unable_to_update) > 0:
        print("  ...Unable to update the following datasets:")
        for key in unable_to_update:
            print(f"    {key}")
    else:
        print("  ...All datasets updated.")

else:
    print("  ...Yes, nothing to update.")