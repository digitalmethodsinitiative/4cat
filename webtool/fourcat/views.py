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

@app.route('/string_query/<string:body_query>/<string:subject_query>/<int:full_thread>/<int:min_timestamp>/<int:max_timestamp>')
def string_query(body_query, subject_query, full_thread=0, min_timestamp=0, max_timestamp=0):
	"""
	AJAX URI for various forms of substring querying

	:param	body_query		str,	Query string for post body. Can be 'empty'.
	:param	subject_query	str,	Query string for post subject. Can be 'empty'.
	:param	full_query		bool,	Whether data from the full thread should be returned.
									Only works when subject is queried.  
	:param	min_timestamp	str,	Min timestamps to search for
	:param	max_timestamp	str,	Max timestamps to search for

	"""

	# Security
	body_query = re.escape(body_query)
	# Make connections to database with backend library - safe enough?
	log = Logger()
	db = Database(logger=log)
	queue = JobQueue(log, db)

	# Queue query
	query = SearchQuery(query=body_query, parameters={
		"body_query": str(body_query),
		"subject_query": str(subject_query),
		"full_thread": bool(full_thread),
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
				return(results)
			return('http://localhost/fourcat/data/' + query.data["query"] + '-' + query_key + '.csv')
		
		return(results)

	else:
		return("no_file")