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

@app.route('/string_query/<string:body_query>/<string:subject_query>/<int:full_thread>/<int:dense_threads>/<int:dense_percentage>/<int:dense_length>/<int:min_timestamp>/<int:max_timestamp>')
def string_query(body_query, subject_query, full_thread=0, dense_threads=0, dense_percentage=15, dense_length=30, min_timestamp=0, max_timestamp=0):
	"""
	AJAX URI for various forms of substring querying

	:param	body_query					str,	Query string for post body. Can be 'empty'.
	:param	subject_query				str,	Query string for post subject. Can be 'empty'.
	:param	full_query					int,	Whether data from the full thread should be returned (0-1).
												Only works when subject is queried.  
	:param	dense_threads				int,	Whether to check for keyword-dense threads (0-1).
	:param	dense_percentage			int,	Minimum percentage of posts in thread containing keyword (>15%).
	:param	dense_length				int,	Minimum thread length for keyword-dense threads (>30).
	:param	min_timestamp				int,	Min date in UTC timestamp
	:param	max_timestamp				int,	Max date in UTC timestamp

	"""

	# Security
	#body_query = re.escape(body_query)

	# Make connections to database with backend library - safe enough?
	log = Logger()
	db = Database(logger=log)
	queue = JobQueue(log, db)

	# Queue query
	query = SearchQuery(query=body_query, parameters={
		"body_query": str(body_query).replace("-", " "),
		"subject_query": str(subject_query).replace("-", " "),
		"full_thread": bool(full_thread),
		"dense_threads": bool(dense_threads),
		"dense_percentage": int(dense_percentage),
		"dense_length": int(dense_length),
		"min_date": int(min_timestamp),
		"max_date": int(max_timestamp)
		}, db=db)
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

	log = Logger()
	db = Database(logger=log)
	query = SearchQuery(key=query_key, db=db)

	results = query.check_query_finished()

	if results:

		# custom stuff for debugging
		if app.debug == True:
			if results == 'empty_file':
				return results
			return 'http://localhost/fourcat/data/' + query.data["query"] + '-' + query_key + '.csv'
		
		return results

	else:
		return "no_file"