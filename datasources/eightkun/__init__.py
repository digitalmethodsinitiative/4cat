# Use default data source init function
from common.lib.helpers import init_datasource as base_init_datasource
from datasources.fourchan import init_datasource

# Internal identifier for this data source
DATASOURCE = "eightkun"
NAME = "8kun"
IS_LOCAL = True