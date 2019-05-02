"""
Initialize Reddit data source
"""

# An init_datasource function is expected to be available to initialize this
# data source. A default function that does this is available from the
# backend helpers library.
from backend.lib.helpers import init_datasource

# Internal identifier for this platform
#
# This name is to be used whenever referring to the platform or a property of
# it. For example, 4CAT will expect the search worker to look for jobs of the
# type "4chan-search" if the PLATFORM is "4chan".
#
# Likewise, this is the identifier used in the config file to configure what
# boards are available for this platform (through the PLATFORMS setting).
PLATFORM = "reddit"