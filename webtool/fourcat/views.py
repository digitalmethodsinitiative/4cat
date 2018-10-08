import sys
import os
sys.path.append(os.getcwd())
#import lib.queue
import backend.config
import pandas as pd
import json
import time
from backend.lib.database import Database
from backend.lib.logger import Logger
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
	db = Database(logger=log)
	
	# Should integrate queue.addJob() when importing gets figured out
	
	db.insert("jobs", data={
		"jobtype": "query",
		"details": json.dumps({"str_query": "skyrim", "col_query": "body_vector"}),
		"timestamp": int(time.time()),
		"remote_id": 0,
		"claim_after": 0
		}, safe=True, constraints=("jobtype", "remote_id"))

	return('<h1>Testing</h1>')
