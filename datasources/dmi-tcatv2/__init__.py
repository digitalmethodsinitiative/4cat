"""
Initialize data source that interfaces with DMI-TCAT query bins
"""

# An init_datasource function is expected to be available to initialize this
# data source. A default function that does this is available from the
# backend helpers library.
from common.lib.helpers import init_datasource

# Internal identifier for this data source
DATASOURCE = "dmi-tcatv2"
NAME = "DMI-TCAT Search (MySQL)"
