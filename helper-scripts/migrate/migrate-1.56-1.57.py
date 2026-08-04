# Settings provenance: record which module declares each setting, so a setting
# that nothing declares any more can be told apart from one whose extension is
# merely uninstalled, disabled, or failed to import.
#
# Creates two tables. No back-fill: the declarations table is populated by the
# back-end on its next boot, for everything that is actually declared then.
# Settings already in the database that nothing declares stay unattributed on
# purpose - guessing an owner from a name prefix would be inventing provenance
# we do not have, and unattributed is the class that is never auto-removed.
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

print("  Creating settings_declarations table...")
db.execute("""
CREATE TABLE IF NOT EXISTS settings_declarations (
  name                   TEXT PRIMARY KEY,
  declared_by            TEXT DEFAULT '' NOT NULL,
  owner_kind             TEXT DEFAULT 'core' NOT NULL,
  extension_id           TEXT DEFAULT NULL,
  category               TEXT DEFAULT '' NOT NULL,
  category_label         TEXT DEFAULT NULL,
  is_managed             BOOLEAN DEFAULT FALSE,
  first_seen             INTEGER DEFAULT 0,
  last_seen              INTEGER DEFAULT 0,
  last_definition        TEXT DEFAULT NULL
);
""")

print("  Creating settings_archive table...")
db.execute("""
CREATE TABLE IF NOT EXISTS settings_archive (
  name                   TEXT DEFAULT '' NOT NULL,
  value                  TEXT DEFAULT '{}' NOT NULL,
  tag                    TEXT DEFAULT '' NOT NULL,
  declared_by            TEXT DEFAULT NULL,
  archived_at            INTEGER DEFAULT 0,
  archived_by            TEXT DEFAULT NULL
);
""")

db.commit()

known = db.fetchone("SELECT COUNT(DISTINCT name) AS num FROM settings")
print(f"  {known['num']} settings in the database; they will be attributed on the next back-end boot.")
print("  - done!")
