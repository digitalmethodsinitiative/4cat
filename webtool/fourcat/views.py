import sys
import os

sys.path.insert(0, os.path.dirname(__file__) +  '/../../backend')
import lib.queue
import backend.config
import pandas as pd
import json
import time
from lib.database import Database
from lib.logger import Logger
from fourcat import app

"""

Main views for the 4CAT front-end

"""

@app.route('/', methods=['GET','POST'])
def show_index():
	"""
	Test the backend functions for substring querying
	"""
	log = Logger()
	query_queue = lib.queue.JobQueue(logger=log)
	db = Database(logger=log)
	
	query_queue.add_job("query", details={"str_query": "skyrim", "col_query": "body_vector"})

	# db.insert("jobs", data={
	# 	"jobtype": "query",
	# 	"details": json.dumps({"str_query": "skyrim", "col_query": "body_vector"}),
	# 	"timestamp": int(time.time()),
	# 	"remote_id": 0,
	# 	"claim_after": 0
	# 	}, safe=True, constraints=("jobtype", "remote_id"))

	return('<h1>Testing</h1>')
