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

# the separate LLM server settings were consolidated into one overarching 'llm.providers' setting
print("  Checking if llm.providers setting exists...")
has_setting = db.fetchone(
    "SELECT COUNT(*) AS num FROM settings WHERE name = 'llm.providers'"
)

if has_setting["num"] > 0:
    print("    ...exists, deleting old settings without overwriting")
else:
    print("    ...does not exist, filling with currently configured proviers")
    provider_type = db.fetchone("SELECT value FROM settings WHERE name = 'llm.provider_type'")
    providers = {}
    if not provider_type or not provider_type.get("value"):
        print("    ...no provider currently configured")
        
    else:
        provider_type = provider_type["value"]
        try:
            url = db.fetchone("SELECT value FROM settings WHERE name = 'llm.server'")["value"]
            host = url.split("/")[2] if "://" in url else "localhost"
            auth_header = db.fetchone("SELECT value FROM settings WHERE name = 'llm.auth_type'")["value"]
            auth_key = db.fetchone("SELECT value FROM settings WHERE name = 'llm.auth_key'")["value"]
            provider_name = db.fetchone("SELECT value FROM settings WHERE name = 'llm.host_name'")["value"]
            provider_id = f"{provider_type}-{host}"

            # vLLM and LM Studio are both openai-like
            provider_type = {"ollama": "ollama"}.get(provider_type, "openai-like")
            providers[provider_id] = {
                "name": provider_name,
                "type": provider_type,
                "url": url,
                "auth_header": auth_header,
                "auth_key": auth_key,
                "_id": provider_id
            }
        except (TypeError, KeyError):
            print("    ...provider configured but settings are incomplete, not migrating")

        # add API models, always present
        providers["thirdparty-models"] = {
        "name": "Third-party models",
        "type": "api",
        "url": "",
        "auth_header": "",
        "auth_key": "",
        "_id": "thirdparty-models"
    }

    db.insert("settings", {"name": "llm.providers", "value": json.dumps(providers)})
    print(f"    ...added {len(providers)} providers")

print("  Cleaning up old settings")
db.execute("DELETE FROM settings WHERE name LIKE 'llm.%' AND name NOT IN ('llm.providers', 'llm.available_models', 'llm.access')")

print("  Removing all known models (will be re-indexed on 4CAT restart)")
db.upsert("settings", {"name": "llm.available_models", "value": "{}"})

print("  - done!")
