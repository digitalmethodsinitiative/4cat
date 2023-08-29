# Add 'tags' column to user table
# and 'tag' column to settings table
# and migrate settings and so on
import json
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "'/../..")
from common.lib.database import Database
from common.lib.logger import Logger

log = Logger(output=True)
from common.config_manager import config

db = Database(logger=log, dbname=config.get('DB_NAME'), user=config.get('DB_USER'), password=config.get('DB_PASSWORD'),
              host=config.get('DB_HOST'), port=config.get('DB_PORT'), appname="4cat-migrate")

# -----------------------------------------------
#  Add tag colums to keep track of per-tag config
# -----------------------------------------------
print("  Checking if users table has a column 'tags'...")
has_column = db.fetchone(
    "SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'tags'")
if has_column["num"] == 0:
    print("  ...No, adding.")
    db.execute("ALTER TABLE users ADD COLUMN tags JSONB DEFAULT '[]'")
    db.commit()
else:
    print("  ...Yes, nothing to update.")

print("  Checking if users table has a column 'timestamp_created'...")
has_column = db.fetchone(
    "SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'timestamp_created'")
if has_column["num"] == 0:
    print("  ...No, adding.")
    db.execute("ALTER TABLE users ADD COLUMN timestamp_created INTEGER DEFAULT 0")
    db.commit()
else:
    print("  ...Yes, nothing to update.")

print("  Checking if settings table has a column 'tag'...")
has_column = db.fetchone(
    "SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'settings' AND column_name = 'tag'")
if has_column["num"] == 0:
    print("  ...No, adding.")
    db.execute("ALTER TABLE settings ADD COLUMN tag TEXT DEFAULT ''")
    db.commit()
else:
    print("  ...Yes, nothing to update.")

print("  Ensuring uniqueness of settings...")
index_name = db.fetchone("SELECT constraint_name FROM information_schema.table_constraints WHERE table_schema = 'public' AND table_name = 'settings' AND constraint_type = 'PRIMARY KEY'")
if index_name:
    db.execute(f"ALTER TABLE settings DROP CONSTRAINT {index_name['constraint_name']}")

db.execute("CREATE UNIQUE INDEX IF NOT EXISTS unique_setting ON settings (name, tag);")

# ---------------------------------------------
#      Ensure admin users are still admins
# ---------------------------------------------
print("  Checking if users table has a column 'is_admin'...")
has_column = db.fetchone(
    "SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'is_admin'")
if has_column["num"] != 0:
    print("  ...yes, giving all admins the 'admin' user tag...")
    for admin in db.fetchall("SELECT * FROM users WHERE is_admin = True"):
        try:
            tags = json.loads(admin["tags"])
        except (TypeError, ValueError):
            tags = []

        if "admin" not in tags:
            tags.insert(0, "admin")

        print(f"  ...admin user {admin['name']}")
        db.update("users", where={"name": admin["name"]}, data={"tags": json.dumps(tags)})

    print("  Dropping 'is_admin' column from users table...")
    try:
        db.execute("ALTER TABLE users DROP COLUMN is_admin")
        print("  ...column dropped")
    except Exception:
        print("  ...column already dropped")
else:
    print("  ...no, already migrated")

# ---------------------------------------------
#  Create separate table for dataset ownership
# ---------------------------------------------
print("  Ensuring datasets_owners table exists...")
db.execute("""
CREATE TABLE IF NOT EXISTS datasets_owners (
    "name" text DEFAULT 'anonymous'::text,
    key text NOT NULL,
    role TEXT DEFAULT 'owner'
);
""")
db.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS dataset_owners_user_key_idx ON datasets_owners("name" text_ops,key text_ops);
""")

# ---------------------------------------------
#  Migrate dataset ownership to new structure
# ---------------------------------------------
print("  Checking if datasets table has a column 'owner'...")
has_column = db.fetchone(
    "SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'datasets' AND column_name = 'owner'")
if has_column["num"] != 0:
    print("  ...column exists")
    print("  Migrating dataset ownership to datasets_owners table...")
    owners = db.fetchall("SELECT key, owner AS name FROM datasets")
    for owner in owners:
        db.insert("datasets_owners", data=owner, safe=True)

    print(f"  ...migrated ownership for {len(owners)} datasets")
    print("  Renaming 'owner' column to 'creator'...")
    db.execute("ALTER TABLE datasets RENAME COLUMN owner TO creator")
    print("  ...done")
else:
    print("  ...column does not exists, assuming ownership has already been migrated.")

# ---------------------------------------------
#       Ensure admin tag already exists
# ---------------------------------------------
print("  Creating privilege settings for 'admin' user tag")
admin_keys = ("can_view_status", "can_manage_users", "can_manage_settings", "can_manage_datasources",
              "can_manage_notification", "can_manage_tags", "can_restart")
for admin_key in admin_keys:
    print(f"  - privileges.admin.{admin_key} = True")
    config.set(f"privileges.admin.{admin_key}", True, tag="admin")

config.set(f"privileges.can_view_all_datasets", True, tag="admin")
config.set(f"privileges.can_view_private_datasets", True, tag="admin")

# ---------------------------------------------
#         More consistent setting names
# ---------------------------------------------
print("  Migrating renamed settings")
changes = {
    "dmi-tcat.instances": "dmi-tcat-search.instances",
    "tiktok-urls.proxies": "tiktok-urls-search.proxies",
    "tiktok-urls.proxies.wait": "tiktok-urls-search.proxies.wait",
    "fourchan.boards": "fourchan-search.boards",
    "fourchan.no_scrape": "fourchan-search.no_scrape",
    "fourchan.interval": "fourchan-search.interval",
    "fourchan.image_interval": "fourchan-search.image_interval",
    "4chan-thread.save_images": "fourchan-search.save_images",
    "eightchan.boards": "eightchan-search.boards",
    "eightchan.no_scrape": "eightchan-search.no_scrape",
    "eightchan.interval": "eightchan-search.interval",
    "eightkun.boards": "eightkun-search.boards",
    "eightkun.no_scrape": "eightkun-search.no_scrape",
    "eightkun.interval": "eightkun-search.interval",
    "image_downloader.MAX_NUMBER_IMAGES": "image-downloader.max",
    "video_downloader.ffmpeg-path": "video-downloader.ffmpeg_path",
    "video_downloader.MAX_NUMBER_VIDEOS": "video-downloader.max",
    "video_downloader.MAX_VIDEO_SIZE": "video-downloader.max-size",
    "video_downloader.DOWNLOAD_UNKNOWN_SIZE": "video-downloader.allow-unknown-size",
    "video_downloader.allow-indirect": "video-downloader.allow-indirect",
    "video_downloader.allow-multiple": "video-downloader.allow-multiple",
    "image-downloader-telegram.MAX_NUMBER_IMAGES": "image-downloader-telegram.max",
    "text_from_images.DMI_OCR_SERVER": "text-from-images.server_url",
    "dmi-tcat.database_instances": "dmi-tcatv2-search.database_instances",
    "pix-plot.PIXPLOT_SERVER": "pix-plot.server_url",
    "tcat-auto-upload.TCAT_SERVER": "tcat-auto-upload.server_url",
    "tcat-auto-upload.TCAT_TOKEN": "tcat-auto-upload.token",
    "tcat-auto-upload.TCAT_USERNAME": "tcat-auto-upload.username",
    "tcat-auto-upload.TCAT_PASSWORD": "tcat-auto-upload.password",
    "4cat.datasources": "datasources.enabled",
    "expire.datasources": "datasources.expiration"
}
for from_name, to_name in changes.items():
    db.execute("UPDATE settings SET name = %s WHERE name = %s", (to_name, from_name))
    print(f"  - {from_name} -> {to_name}")

# ------------------------------------------------
# Migrate 'user data' values that are now settings
# ------------------------------------------------
changes = {
    "reddit.can_query_without_keyword": "reddit-search.can_query_without_keyword",
    "4chan.can_query_without_keyword": "fourchan-search.can_query_without_keyword",
    "telegram.can_query_all_messages": "telegram-search.can_query_all_messages"
}
for from_name, to_name in changes.items():
    print(f"  - {from_name} -> {to_name}")
    users = db.fetchall(f"SELECT * FROM users WHERE userdata::json->>'{from_name}' IS NOT NULL")
    for user in users:
        userdata = json.loads(user["userdata"])
        config.set(to_name, userdata[from_name], tag=f"user:{user['name']}")
        del userdata[from_name]
        db.update("users", where={"name": user["name"]}, data={"userdata": json.dumps(userdata)}, commit=False)

# ---------------------------------------------
# New dataset identifiers - these were changed
# for boring reasons, but this is the price:
# ---------------------------------------------
print("  Updating dataset and job identifiers")
changes = {
    "8kun": "eightkun",
    "8chan": "eightchan",
    "4chan": "fourchan",
}
for from_name, to_name in changes.items():
    print("  ...updating jobs")
    db.execute(f"UPDATE jobs SET jobtype = REPLACE(jobtype, '{from_name}', '{to_name}') WHERE jobtype LIKE '{from_name}-%'")

    print("  ...updating dataset types")
    db.execute(f"UPDATE datasets SET type = REPLACE(type, '{from_name}', '{to_name}') WHERE type LIKE '{from_name}-%'")

    # ugh
    print("  ...updating dataset parameters")
    for dataset in db.fetchall(f"SELECT * FROM datasets WHERE parameters::json->>'datasource' = '{from_name}' OR parameters::json->>'type' LIKE '{from_name}-%'"):
        parameters = json.loads(dataset["parameters"])
        if "datasource" in parameters:
            parameters["datasource"] = to_name

        if parameters.get("type", "").startswith(from_name + "-"):
            parameters["type"] = parameters["type"].replace(from_name, to_name)

        db.update("datasets", where={"key": dataset["key"]}, data={"parameters": json.dumps(parameters)}, commit=False)

db.commit()
print("  Done!")
