# Ensure unique metrics index exists
import sys
import os

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

print("  Making sure unique index exists for datasource metrics table...")
db.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS unique_metrics
    ON metrics (metric, datasource, board, date);
""")

print("  Setting interval for datasource_metrics job...")
job_exists = db.fetchone("SELECT COUNT(*) FROM jobs AS count WHERE jobtype = 'datasource-metrics'")
if job_exists["count"] > 0:
    db.update("jobs", where={"jobtype": "datasource-metrics"}, data={"interval": 43200})
print("  - done!")