"""
Delete all files from the results folder that are not linked to a query
"""
import glob
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/..")
from common.lib.database import Database
from common.lib.logger import Logger
from common.lib.dataset import DataSet
import config

logger = Logger()
database = Database(logger=logger, appname="result-cleaner")

os.chdir(config.PATH_DATA)
files = glob.glob("*.*")

for file in files:
	key = file.split(".")[0].split("-")[-1]
	try:
		query = DataSet(key=key, db=database)
	except TypeError:
		print("Not linked to a query: %s" % file)
		os.unlink(config.PATH_DATA + "/" + file)