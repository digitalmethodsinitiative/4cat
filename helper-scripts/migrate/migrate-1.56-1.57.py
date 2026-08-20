# Settings provenance: record which module declares each setting, so a setting
# that nothing declares any more can be told apart from one whose extension is
# merely uninstalled, disabled, or failed to import.
#
# Creates two tables. Almost no back-fill: the declarations table is populated
# by the back-end on its next boot, for everything that is actually declared
# then. Settings already in the database that nothing declares stay unattributed
# on purpose - guessing an owner from a name prefix would be inventing
# provenance we do not have, and unattributed is the class that is never
# auto-removed. The exception is the retired core settings below, which are
# attributed because we know what they were, and because an archived setting
# with no declaration could never be archived again once restored.
#
# It then clears out a hand-checked list of core settings for features 4CAT no
# longer has. Those cannot be found automatically for the reason above, so the
# list is written out below with what became of each one.
import time
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
  declared               BOOLEAN DEFAULT FALSE NOT NULL,
  is_indirect            BOOLEAN DEFAULT FALSE,
  first_seen             INTEGER DEFAULT 0,
  last_seen              INTEGER DEFAULT 0,
  last_definition        TEXT DEFAULT NULL,
  absent_since           INTEGER DEFAULT NULL
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

db.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS unique_archived_setting
  ON settings_archive (
    name, tag
  );
""")

db.commit()

# Core settings that 4CAT no longer has, with what became of each.
# This is a hand-checked list, because the settings provenance system
# is only being built now.
#
# Only settings that were part of 4CAT itself are listed. Settings belonging to
# an extension are never removed by 4CAT, even when the extension has renamed
# them, because the extension may be re-installed at any version.
RETIRED_CORE_SETTINGS = {
    # renamed in the Explorer revamp (#428, 6268a5d71)
    "datasources._intro": "renamed to datasources.intro",
    "datasources._intro2": "renamed to datasources.intro2",

    # renamed in 'Pre-Ruff stuff' (#503)
    "4cat.access_request_limit": "renamed to 4cat.allow_access_request_limiter",

    # the option to serve results over the old-style links went away in
    # 'remove now unused 4CAT config setting, remove show_' (2026-04-28)
    # i.e. me developing stuff I immediately removed...
    "4cat.allow_legacy_result_links": "feature removed",
    "privileges.allow_legacy_result_links": "feature removed",

    # the datasource scheduler was taken out again in 'excise scheduler merge'
    # (2024-08-29)
    "privileges.can_schedule_datasources": "feature removed",

    # the Reddit datasource is no longer part of 4CAT
    "api.reddit.client_id": "datasource removed",
    "api.reddit.secret": "datasource removed",
    "reddit-search.can_query_without_keyword": "datasource removed",

    # removed with the 'annotate with LLMs' processor in 450242e77 (2025-09-29),
    # which is to be rebuilt on top of llm-prompter.
    "dmi-service-manager.stormtrooper_enabled": "processor removed, to be rebuilt as llm-prompter",
    "dmi-service-manager.stormtrooper_intro-1": "processor removed, to be rebuilt as llm-prompter",
    "dmi-service-manager.stormtrooper_models": "processor removed, to be rebuilt as llm-prompter",

    # per-processor proxy settings gave way to the 4CAT-wide proxy pool
    # (#487, 2025-06-10). processors/metrics/url_titles.py declared these
    "url-metadata.proxies": "superseded by the 4CAT-wide proxy pool",
    "url-metadata.proxies.wait": "superseded by the 4CAT-wide proxy pool",

    # processors/visualisation/download_telegram_files.py takes an amount per
    # run now, rather than reading a configured maximum
    "file-downloader-telegram.max_files": "replaced by a per-run option",

    # the VK datasource asks for credentials per query and declares no settings
    # (these might only have be my dev settings, but I am not positive)
    "vk.a_info": "datasource declares no settings",
    "vk.app_id": "datasource declares no settings",
    "vk.client_secret": "datasource declares no settings",
}

print("  Archiving settings for features 4CAT no longer has...")
now = int(time.time())
archived = 0
for setting, reason in RETIRED_CORE_SETTINGS.items():
    stored = db.fetchall("SELECT * FROM settings WHERE name = %s", (setting,))
    if not stored:
        continue

    # every one of these was part of 4CAT itself, so record that before moving
    # it aside. Without a declaration row, restoring one - if only to see what
    # was configured - would bring it back as 'unknown', which the settings
    # panel will not archive again: a one-way trip out of the archive.
    db.insert("settings_declarations", {
        "name": setting,
        "declared_by": "core:config_definition",
        "owner_kind": "core",
        # retired, so nothing declares it - which together with absent_since is
        # what lets it be archived again if it is ever restored
        "declared": False,
        "absent_since": now
    }, safe=True, commit=False)

    for row in stored:
        # moved rather than deleted, so a wrong call here can be undone from the
        # settings panel instead of costing whatever was configured
        db.insert("settings_archive", {
            "name": row["name"],
            "value": row["value"],
            "tag": row["tag"],
            "declared_by": "core:config_definition",
            "archived_at": now,
            "archived_by": "migrate-1.56-1.57"
        }, commit=False)

    db.delete("settings", where={"name": setting}, commit=False)
    archived += len(stored)
    print(f"    {setting} ({reason})")

db.commit()
print(f"  {archived} stored value(s) archived. They can be restored from the settings panel.")

known = db.fetchone("SELECT COUNT(DISTINCT name) AS num FROM settings")
print(f"  {known['num']} settings in the database; they will be attributed on the next back-end boot.")
print("  - done!")
