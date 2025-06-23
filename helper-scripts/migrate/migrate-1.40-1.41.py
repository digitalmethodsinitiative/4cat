# Ensure unique metrics index exists
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

db = Database(logger=log, dbname=db_config["db_name"], user=db_config["db_user"], password=db_config["db_password"],
              host=db_config["db_host"], port=db_config["db_port"], appname="4cat-migrate")

print("  Changing 'count' column type to BIGINT...")
db.execute("ALTER TABLE metrics ALTER COLUMN count TYPE BIGINT")

print("  Ensuring uniqueness of existing stats...")
# due to an earlier bug, some days have multiple metrics
# the higher one is always correct
# this is a bit annoying to fix since the rows have no unique ID so we just
# throw away everything and insert deduplicated values
all_stats = db.fetchall("SELECT * FROM metrics")
sorted_stats = {}
deletable = {}
for stat in all_stats:
    if stat["metric"] not in sorted_stats:
        sorted_stats[stat["metric"]] = {}

    if stat["date"] not in sorted_stats[stat["metric"]]:
        sorted_stats[stat["metric"]][stat["date"]] = {}

    if stat["datasource"] not in sorted_stats[stat["metric"]][stat["date"]]:
        sorted_stats[stat["metric"]][stat["date"]][stat["datasource"]] = {}

    if stat["board"] not in sorted_stats[stat["metric"]][stat["date"]][stat["datasource"]]:
        sorted_stats[stat["metric"]][stat["date"]][stat["datasource"]][stat["board"]] = stat["count"]
    else:
        sorted_stats[stat["metric"]][stat["date"]][stat["datasource"]][stat["board"]] = max(sorted_stats[stat["metric"]][stat["date"]][stat["datasource"]][stat["board"]], stat["count"])

db.execute("DELETE FROM metrics")
for metric, metric_stats in sorted_stats.items():
    for date, date_stats in metric_stats.items():
        for source, source_stats in date_stats.items():
            for board, value in source_stats.items():
                db.insert("metrics", {
                    "metric": metric,
                    "datasource": source,
                    "board": board,
                    "date": date,
                    "count": value
                }, commit=False)

db.commit()

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