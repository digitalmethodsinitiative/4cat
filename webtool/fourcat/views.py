import sys
import os
sys.path.insert(0, os.path.dirname(__file__) +  '/../../backend')
import lib.queue
import backend.config
import pandas as pd
import json
import time
import re
from flask import Flask, render_template, url_for
from lib.database import Database
from lib.logger import Logger
from fourcat import app

"""

Main views for the 4CAT front-end

"""

@app.route('/')
def show_index():
	"""
	Index page: main tool frontend
	"""
	return render_template('fourcat.html')

@app.route('/string_query/<searchquery>')
def string_query(searchquery):
	"""
	AJAX URI for substring querying
	"""

	# for security
	searchquery = re.escape(searchquery)

	# make connections to database with backend library
	log = Logger()
	query_queue = lib.queue.JobQueue(logger=log)
	db = Database(logger=log)
	
	# add job with respective query string
	query_queue.add_job("query", details={"str_query": searchquery, "col_query": "body_vector"})

	return 'success'

@app.route('/check_query/<searchquery>', methods=['GET','POST'])
def check_query(searchquery):
	"""
	AJAX URI to check whether query has been completed.
	"""
	csv_path = os.path.dirname(__file__) + '/static/data/filters/mentions_' + searchquery + '.csv'

	print(csv_path)
	
	if os.path.isfile(csv_path):
		return 'file_exists'
	else:
		return 'no_file'