# Add some privileges that should be enabled by default for admins
import configparser
import subprocess
import shutil
import shlex
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

print("  Adding default privileges for the 'admin' tag...")
privileges = ("privileges.admin.can_manipulate_all_datasets", "privileges.admin.can_manipulate_notifications")
for privilege in privileges:
    print(f"  ...{privilege}")
    db.insert("settings", data={"name": privilege, "value": "true", "tag": "admin"}, safe=True)