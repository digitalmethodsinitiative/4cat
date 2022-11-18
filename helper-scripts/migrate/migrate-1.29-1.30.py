# For imageboard data sources,
# create an index on the basis of a thread's archived or deleted timestamps.
# This is used to quickly fetch the last few threads if they haven't been marked
# as inactive (i.e. archived or deleted). We need these to check the status of these
# threads after they've disappeared off the index.

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "'/../..")
from common.lib.database import Database
from common.lib.logger import Logger

log = Logger(output=True)
import common.config_manager as config

db = Database(logger=log, dbname=config.get('DB_NAME'), user=config.get('DB_USER'), password=config.get('DB_PASSWORD'),
              host=config.get('DB_HOST'), port=config.get('DB_PORT'), appname="4cat-migrate")

# New format for datasource enabling and settings
datasources = config.get("DATASOURCES")
if type(datasources) is dict:
    new_datasources = list(datasources.keys())

    # migrate settings
    for platform in ("4chan", "8kun", "8chan"):
        for setting in ("boards", "no_scrape", "autoscrape", "interval"):
            if platform in datasources and datasources[platform].get(setting):
                print(f"  Migrating setting {platform}.{setting}...")
                config.set_or_create_setting(platform.replace("4", "four").replace("8", "eight") + "." + setting,
                                             datasources[platform][setting], raw=False)

    for platform in ("dmi-tcat", "dmi-tcatv2"):
        for setting in ("instances",):
            if platform in datasources and datasources[platform].get(setting):
                print(f"  Migrating setting {platform}.{setting}...")
                config.set_or_create_setting(platform + "." + setting, datasources[platform][setting], raw=False)

    print(f"  Migrating data source-specific expiration settings...")
    expiration = {datasource: {"timeout": info["expire-datasets"], "allow_optout": False} for datasource, info in
                  datasources.items() if "expire-datasets" in info}
    config.set_or_create_setting("expire.datasources", expiration, raw=False)

    print("  Updating DATASOURCES setting...")
    config.set_or_create_setting("4cat.datasources", new_datasources, raw=False)
    config.delete_setting("DATASOURCES")

print("  Deleting and migrating deprecated settings...")
if config.get("IMAGE_INTERVAL"):
    print("  - IMAGE_INTERVAL -> fourchan.image_interval")
    config.set_or_create_setting("fourchan.image_interval", config.get("IMAGE_INTERVAL", 60), raw=False)
    config.delete_setting("IMAGE_INTERVAL")

print("  - WARN_EMAILS, WARN_INTERVAL -> removed")
config.delete_setting("WARN_EMAILS")
config.delete_setting("WARN_INTERVAL")

print("  Creating new indexes for enabled imageboard datasources...")

imageboards_enabled = False

# Check for 8kun
is_8kun = db.fetchone(
    "SELECT EXISTS ( SELECT FROM information_schema.tables WHERE table_name = %s )" % "'threads_8kun'")
if is_8kun["exists"]:
    imageboards_enabled = True

    print("  Creating 'threads_archiving_8kun' index if it didn't exist already...")

    db.execute("""
        CREATE INDEX IF NOT EXISTS threads_archiving_8kun
          ON threads_8kun (
            timestamp_deleted, timestamp_archived, timestamp_modified, board
          );
    """)

    db.commit()

# Check for 4chan
is_4chan = db.fetchone(
    "SELECT EXISTS ( SELECT FROM information_schema.tables WHERE table_name = %s )" % "'threads_4chan'")
if is_4chan["exists"]:
    imageboards_enabled = True

    print("  Creating 'threads_archiving_4chan' index if it didn't exist already...")
    db.execute("""
        CREATE INDEX IF NOT EXISTS threads_archiving_4chan
          ON threads_4chan (
            timestamp_deleted, timestamp_archived, timestamp_modified, board
          );
    """)

    db.commit()

if not imageboards_enabled:
    print("  No imageboard data sources enabled")
else:
    print("  Done!")
