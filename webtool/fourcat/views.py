import os
import re
from flask import Flask, render_template, url_for
from fourcat import app

from backend.lib.database import Database
from backend.lib.logger import Logger
from backend.lib.queue import JobQueue

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
@app.route('/string_query/<searchquery>/<min_timestamp>/<max_timestamp>')
def string_query(searchquery, min_timestamp='none', max_timestamp='none'):
	"""
	AJAX URI for substring querying

	:param	searchquery		str, the string to query for
	:param	timestamps		str, min and max timestamps to search for, separated by #
	"""

	# for security
	searchquery = re.escape(searchquery)

	# make connections to database with backend library
	log = Logger()
	db = Database(logger=log)
	query_queue = JobQueue(logger=log, database=db)
	
	# add job with respective query string
	query_queue.add_job("query", details={"str_query": searchquery, "col_query": "body_vector", "min_timestamp": min_timestamp, "max_timestamp": max_timestamp})

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