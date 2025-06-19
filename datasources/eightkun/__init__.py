# Use default data source init function
from common.lib.helpers import init_datasource as base_init_datasource  # noqa: F401
from common.lib.helpers import init_datasource as init_datasource

# Internal identifier for this data source
DATASOURCE = "eightkun"
NAME = "8kun"
IS_LOCAL = True
