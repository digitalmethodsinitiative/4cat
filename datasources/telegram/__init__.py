"""
Initialize The Guardian data source
"""

# An init_datasource function is expected to be available to initialize this
# data source. A default function that does this is available from the
# backend helpers library.
from common.lib.helpers import init_datasource

# Internal identifier for this data source
DATASOURCE = "telegram"
NAME = "Telegram"

USER_SETTINGS = ["api_id", "api_key", "phone", "security_code"]