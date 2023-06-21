# Add 'tags' column to user table
# and 'tag' column to settings table
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

print("  Checking if users table has a column 'tags'...")
has_column = db.fetchone(
    "SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'tags'")
if has_column["num"] == 0:
    print("  ...No, adding.")
    db.execute("ALTER TABLE users ADD COLUMN tags JSONB DEFAULT '{}'")
    db.commit()
else:
    print("  ...Yes, nothing to update.")

print("  Checking if settings table has a column 'tag'...")
has_column = db.fetchone(
    "SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'settings' AND column_name = 'tag'")
if has_column["num"] == 0:
    print("  ...No, adding.")
    db.execute("ALTER TABLE settings ADD COLUMN tag TEXT DEFAULT '{}'")
    db.commit()
else:
    print("  ...Yes, nothing to update.")

print("  Giving all admins the 'admin' user tag...")
for admin in db.fetchall("SELECT * FROM users WHERE is_admin = True"):
    try:
        tags = json.loads(admin["tags"])
    except ValueError:
        tags = {}

    if "admin" not in tags:
        tags.append("admin")

    print(f"  ...admin user {admin['name']}")
    db.update("users", where={"name": admin["name"]}, data={"tags": json.dumps(tags)})

print("  Dropping 'is_admin' column from users table...")
try:
    db.execute("ALTER TABLE users DROP COLUMN is_admin")
    print("  ...column dropped")
except Exception:
    print("  ...column already dropped")

print("  Ensuring datasets_owners table exists...")
db.execute("""
CREATE TABLE IF NOT EXISTS datasets_owners (
    "user" text DEFAULT 'anonymous'::text,
    key text NOT NULL
);
""")
db.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS dataset_owners_user_key_idx ON datasets_owners("user" text_ops,key text_ops);
""")

print("  Checking if users table has a column 'owner'...")
has_column = db.fetchone(
    "SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'owner'")
if has_column:
    print("  ...column exists")
    print("  Migrating dataset ownership to datasets_owners table...")
    owners = db.fetchall("SELECT key, owner FROM datasets")
    for owner in owners:
        db.insert("datasets_owners", data=owner)

    print(f"  ...migrated ownership for {len(owners)} datasets")
    print("  Dropping column...")
    db.execute("ALTER TABLE users DROP COLUMN owner")
    print("  ...done")
else:
    print("  ...column does not exists, assuming ownership has already been migrated.")

db.commit()
print("  Done!")
