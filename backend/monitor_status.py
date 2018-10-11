"""
Backend monitoring script

Exits with code > 0 if potential problems are found, 0 if not. Note that the
user is responsible for running this in regular intervals - e.g. via a
cron job.
"""
import time
import math
import sys
import os

sys.path.insert(0, os.path.dirname(__file__) +  '/../..')
import config

from lib.database import Database
from lib.logger import Logger

concern = False
monitor_interval = 3600

try:
    log = Logger()
except Exception:
    log = None
    concern = True

try:
    log.enable_mailer()
    db = Database(logger=log)
    concern = True

    cutoff = int(time.time()) - monitor_interval
    interval_minutes = math.floor(monitor_interval / 60)

    recent = {
        "posts": db.fetchone("SELECT COUNT(*) AS num FROM posts WHERE timestamp > %s", (cutoff,))["num"],
        "threads": db.fetchone("SELECT COUNT(*) AS num FROM posts WHERE timestamp > %s", (cutoff,))["num"],
        "jobs": db.fetchone("SELECT COUNT(*) as num FROM jobs")["num"]
    }

    if recent["posts"] < config.WARN_POSTS:
        log.warning("%s posts scraped in the past %s minutes. Is the scraper working?" % (interval_minutes, recent["posts"]))
        concern = True

    if recent["threads"] < config.WARN_THREADS:
        log.warning("%s threads scraped in the past %s minutes. Is the scraper working?" % (interval_minutes, recent["threads"]))
        concern = True

    if recent["jobs"] == 0:
        log.warning("No jobs were found queued.")

    if recent["jobs"] > 500:
        log.warning("%s jobs were found qeueud during check." % (recent["jobs"],))

except Exception as e:
    if log:
        log.critical("Exception raised while running monitoring script: %s" % e)
    concern = True


# exit with proper exit code
sys.exit(1) if concern else sys.exit(0)