"""
Miscellaneous helper functions for the 4CAT backend
"""
import inspect
import sys
import os

import config


def get_absolute_folder(folder=""):
	"""
	Get absolute path to a folder

	Determines the absolute path of a given folder, which may be a relative
	or absolute path. Note that it is not checked whether the folder actually exists

	:return string:  Absolute folder path (no trailing slash)
	"""
	if len(folder) == 0 or folder[0] != "/":
		path = os.path.dirname(os.path.dirname(os.path.dirname(__file__))) + "/"  # 4cat root folder
		path += folder
	else:
		path = folder

	path = path[:-1] if len(path) > 0 and path[-1] == "/" else path

	return path


def init_datasource(database, logger, queue, name):
	"""
	Initialize data source

	Queues jobs to scrape the boards that were
	:param database:
	:param logger:
	:param queue:
	:param name:
	:return:
	"""
	if name not in config.PLATFORMS or "boards" not in config.PLATFORMS[name]:
		return

	for board in config.PLATFORMS[name]["boards"]:
		queue.add_job(name + "-board", remote_id=board, interval=60)


class UserInput:
	OPTION_TOGGLE = "toggle"
