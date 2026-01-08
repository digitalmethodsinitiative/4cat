# delete background jobs from queue
# these will be re-added on next restart with the new intervals
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

# Add new admin privilege to manage extensions
print("  Checking for `queue_id` column in jobs table...")
has_column = db.fetchone(
    "SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'jobs' AND column_name = 'queue_id'"
)

if has_column["num"] > 0:
    print("    Jobs table already has column 'queue_id'")
else:
    print("    Adding column 'queue_id' to jobs table...")
    db.execute("ALTER TABLE jobs ADD queue_id TEXT DEFAULT ''")

print("  Creating `jobs_queue` index on jobs table...")
db.execute("CREATE INDEX IF NOT EXISTS job_queue ON jobs (queue_id)")

print("  - done!")
