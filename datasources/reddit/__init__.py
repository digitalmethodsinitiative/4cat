"""
Initialize Reddit data source
"""

# An init_datasource function is expected to be available to initialize this
# data source. A default function that does this is available from the
# backend helpers library.
from common.lib.helpers import init_datasource  # noqa: F401

# Internal identifier for this data source
DATASOURCE = "reddit"
NAME = "Reddit"