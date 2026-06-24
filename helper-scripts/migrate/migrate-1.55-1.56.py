import json
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

# the separate LLM server settings were consolidated into one overarching 'llm.servers' setting
print("  Checking if llm.servers setting exists...")
has_setting = db.fetchone(
    "SELECT COUNT(*) AS num FROM settings WHERE name = 'llm.servers'"
)

if has_setting["num"] > 0:
    print("    ...exists, deleting old settings without overwriting")
else:
    print("    ...does not exist, filling with currently configured proviers")
    server_type = db.fetchone("SELECT value FROM settings WHERE name = 'llm.provider_type'")
    servers = {}
    if not server_type or not server_type.get("value"):
        print("    ...no server currently configured")
        
    else:
        server_type = server_type["value"]
        try:
            url = db.fetchone("SELECT value FROM settings WHERE name = 'llm.server'")["value"]
            host = url.split("/")[2] if "://" in url else "localhost"
            auth_header = db.fetchone("SELECT value FROM settings WHERE name = 'llm.auth_type'")["value"]
            auth_key = db.fetchone("SELECT value FROM settings WHERE name = 'llm.auth_key'")["value"]
            server_name = db.fetchone("SELECT value FROM settings WHERE name = 'llm.host_name'")["value"]
            server_id = f"{server_type}-{host}"

            # vLLM and LM Studio are both openai-like
            server_type = {"ollama": "ollama"}.get(server_type, "openai-like")
            servers[server_id] = {
                "name": server_name,
                "type": server_type,
                "url": url,
                "auth_header": auth_header,
                "auth_key": auth_key,
                "_id": server_id
            }
        except (TypeError, KeyError):
            print("    ...server configured but settings are incomplete, not migrating")

        # add API models, always present
        servers["thirdparty-models"] = {
        "name": "Third-party models",
        "type": "thirdparty",
        "url": "",
        "auth_header": "",
        "auth_key": "",
        "_id": "thirdparty-models"
    }

    db.insert("settings", {"name": "llm.servers", "value": json.dumps(servers)})
    print(f"    ...added {len(servers)} servers")

print("  Cleaning up old settings")
db.execute("DELETE FROM settings WHERE name LIKE 'llm.%' AND name NOT IN ('llm.servers', 'llm.available_models', 'llm.access')")

print("  Removing all known models (will be re-indexed on 4CAT restart)")
db.upsert("settings", {"name": "llm.available_models", "value": "{}", "tag": ""}, constraints=["name", "tag"])

print("  - done!")
