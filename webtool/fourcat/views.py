import os
import re
import config
import pickle as p

from flask import Flask, render_template, url_for
from fourcat import app

from backend.lib.query import SearchQuery
from backend.lib.helpers import get_absolute_folder
from backend.lib.database import Database
from backend.lib.logger import Logger
from backend.lib.queue import JobQueue, JobAlreadyExistsException

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

	# make connections to database with backend library - safe enough?
	log = Logger()
	db = Database(logger=log)
	queue = JobQueue(log, db)

	query = SearchQuery(query=searchquery, parameters={"str_query": searchquery, "col_query": "body_vector", "min_timestamp": min_timestamp, "max_timestamp": max_timestamp}, db=db)
	try:
		queue.add_job(jobtype="query", remote_id=query.key)
	except JobAlreadyExistsException:
		pass

	print("Query queued: %s" % query.key)
	return query.key

@app.route('/check_query/<query_key>', methods=['GET','POST'])
def check_query(query_key):
	"""
	AJAX URI to check whether query has been completed.
	"""

	# load dict with metadata and statuses of already processed queries
	
	log = Logger()
	db = Database(logger=log)
	query = SearchQuery(key=query_key, db=db)


	results = query.get_finished_results_path()

	if results:

		# relative file path for debugging
		if app.debug == True:
			results = 'http://localhost/fourcat/' + config.PATH_DATA + results.split(config.PATH_DATA,1)[1]

		return(results)
	else:
		return("nofile")

	if 1 == 2:
		path_file_status = get_absolute_folder(config.PATH_DATA + '/queries/di_queries.p')

		if os.path.isfile(path_file_status):
			di_queries = p.load(open(path_file_status, 'rb'))
			
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