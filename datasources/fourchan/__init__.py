"""
Initialize 4chan data source
"""

# An init_datasource function is expected to be available to initialize this
# data source. A default function that does this is available from the
# backend helpers library.
from common.lib.helpers import init_datasource as base_init_datasource

import config

# Internal identifier for this data source
#
# This name is to be used whenever referring to the data source or a property
# of it. For example, 4CAT will expect the search worker to look for jobs of
# the type "4chan-search" if the DATASOURCE is "4chan".
#
# Likewise, this is the identifier used in the config file to configure what
# boards are available for this data source (through the DATASOURCES setting).
DATASOURCE = "4chan"

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

	if config.DATASOURCES[name].get("autoscrape", False):
		for board in config.DATASOURCES[name]["boards"]:
			queue.add_job(name + "-board", {}, board, 0, interval)

	base_init_datasource(database, logger, queue, name)