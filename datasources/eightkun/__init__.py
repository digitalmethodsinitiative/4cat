# Use default data source init function
from backend.lib.helpers import init_datasource as base_init_datasource

import config

# Internal identifier for this data source
DATASOURCE = "8kun"
NAME = "8kun"

def init_datasource(database, logger, queue, name):
	"""
	Initialise datasource

	Compounds the base initialisation method by queueing jobs for the board
	scrapers, if those don't exist already.

	:param Database database:  Database connection instance
	:param Logger logger:  Log handler
	:param JobQueue queue:  Job Queue instance
	:param string name:  ID of datasource that is being initialised
	"""
	interval = config.DATASOURCES[name]["interval"]
	for board in config.DATASOURCES[name]["boards"]:
		queue.add_job("8kun-board", {}, board, 0, interval)

	base_init_datasource(database, logger, queue, name)