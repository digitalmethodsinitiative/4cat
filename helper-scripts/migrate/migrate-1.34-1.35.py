# Fix privileges and expiration
import json
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

# Hot fix for missing database initialization column in 1.34
creator_column_check = db.fetchone(
    "SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'datasets' AND column_name = 'creator'")
if creator_column_check["num"] == 0:
    print("  Adding missing 'creator' column to 'datasets' table...")
    db.execute("ALTER TABLE datasets ADD COLUMN creator VARCHAR DEFAULT 'anonymous'")
    db.commit()

print("  Adding default privileges for the 'admin' tag...")
privileges = ("privileges.admin.can_manipulate_all_datasets", "privileges.admin.can_manage_notifications")
for privilege in privileges:
    print(f"  ...{privilege}")
    db.insert("settings", data={"name": privilege, "value": "true", "tag": "admin"}, safe=True)

# expiration was a mistake
# or at least the initial implementation was
print("  Harmonising dataset expiration dates...")
warning_datasets = False
warning_expires = False
datasets = db.fetchall("""
    SELECT * FROM datasets 
     WHERE parameters::json->>'expires-after' IS NOT NULL 
       AND (parameters::json->>'expires-after')::int > 0 
       AND parameters::json->>'keep' IS NULL
""")
if datasets:
    warning_datasets = True
    for dataset in datasets:
        parameters = json.loads(dataset["parameters"])
        if "expires-after" in parameters:
            del parameters["expires-after"]
            db.update("datasets", where={"key": dataset["key"]}, data={"parameters": json.dumps(parameters)})

expires = db.fetchone("SELECT * FROM settings WHERE name = 'expires.timeout'")
if expires:
    try:
        expires = int(expires["value"])
    except (TypeError, ValueError):
        expires = 0

    warning_expires = True

if any([warning_expires, warning_datasets]):
    print("  /!\ /!\ /!\ /!\ /!\ /!\ /!\ /!\ /!\ /!\ /!\ /!\ /!\ ")
    print("                        WARNING!                      ")
    if warning_datasets:
        print("  Some datasets were explicitly marked for deletion. Because")
        print("  it cannot unambiguously be determined whether these should")
        print("  be deleted, they have been unmarked (i.e. they will not")
        print("  automatically be deleted). Use the data source expiration")
        print("  settings to make sure they expire correctly.")
    if warning_expires:
        print("  It is no longer possible to set global expiration timeouts.")
        print("  Instead, these need to be configured per data source. You")
        print("  can do this in the settings panel.")
    print("")
    print("  For this reason, all expiration settings have been reset.")
    print("  Please re-configure via the settings panel and the new")
    print("  dataset bulk management interface in the web interface.")
    print("")
    print("  See the release notes for version 1.35 for more")
    print("  information.")
    print("  /!\ /!\ /!\ /!\ /!\ /!\ /!\ /!\ /!\ /!\ /!\ /!\ /!\ ")

    # reset timeouts for all current expiration settings, for all tags
    db.delete("settings", where={"name": "datasources.expiration"})
    datasources = db.fetchall("SELECT * FROM settings WHERE name = 'datasources.enabled'")
    for setting in datasources:
        db.delete("settings", where=setting)
        try:
            # reset timeouts
            enabled = json.loads(setting["value"])
            db.insert("settings", data={"name": "datasources.expiration", "value": json.dumps({
                datasource: {
                    "enabled": True,
                    "timeout": 0,
                    "allow_optout": False
                } for datasource in enabled
            }), "tag": setting["tag"]})
        except json.JSONDecodeError:
            # invalid setting, deleting is enough
            pass
