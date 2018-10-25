import os
import re
import config
import pickle as p

from flask import Flask, render_template, url_for
from fourcat import app

from backend.lib.helpers import get_absolute_folder
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

	# load dict with metadata and statuses of already processed queries
	path_file_status = get_absolute_folder(config.PATH_DATA + '/queries/di_queries.p')

	if os.path.isfile(path_file_status):
		di_queries = p.load(open(path_file_status, 'rb'))
		print(di_queries)
		if searchquery in di_queries:
			file_status = di_queries[searchquery]
		else:
			file_status = 'processing'
	else: 
		file_status = 'processing'
	
	# check status of query
	if file_status == 'finished':
		# returns string with path to the csv
		csv_path = config.PATH_DATA + '/mentions_' + searchquery + '.csv'
		return csv_path

	elif file_status == 'empty_file':
		# if the query has already been executed, but no results were shown, return empty file notification
		return 'empty_file'

	else:
		return 'nofile'