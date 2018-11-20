import os
import re
import config
import pickle as p

from flask import Flask, render_template, url_for, abort
from fourcat import app

from backend.lib.query import SearchQuery
from backend.lib.helpers import get_absolute_folder
from backend.lib.database import Database
from backend.lib.logger import Logger
from backend.lib.queue import JobQueue, JobAlreadyExistsException

from stop_words import get_stop_words

"""

Main views for the 4CAT front-end

"""

@app.route('/')
def show_index():
	"""
	Index page: main tool frontend
	"""

	boards = config.SCRAPE_BOARDS

	return render_template('fourcat.html', boards=boards)

@app.route('/string_query/<string:board>/<string:body_query>/<string:subject_query>/<int:full_thread>/<int:dense_threads>/<int:dense_percentage>/<int:dense_length>/<int:min_timestamp>/<int:max_timestamp>')
def string_query(board, body_query, subject_query, full_thread=0, dense_threads=0, dense_percentage=15, dense_length=30, min_timestamp=0, max_timestamp=0):
	"""
	AJAX URI for various forms of substring querying

	:param	board						str,	The board to query.
	:param	body_query					str,	Query string for post body. Can be 'empty'.
	:param	subject_query				str,	Query string for post subject. Can be 'empty'.
	:param	exact_match					int,	Whether to perform an exact substring match instead of FTS.
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
	body_query = body_query.replace("[^\p{L}A-Za-z0-9_*-]","");
	subject_query = subject_query.replace("[^\p{L}A-Za-z0-9_*-]","");
	parameters = {
		"board": str(board),
		"body_query": str(body_query).replace("-", " "),
		"subject_query": str(subject_query).replace("-", " "),
		"full_thread": bool(full_thread),
		"dense_threads": bool(dense_threads),
		"dense_percentage": int(dense_percentage),
		"dense_length": int(dense_length),
		"min_date": int(min_timestamp),
		"max_date": int(max_timestamp)
	}

	valid = validateQuery(parameters)

	if valid != True:
		print(valid)
		return "Invalid query. " + valid

	# Queue query
	query = SearchQuery(query=body_query, parameters=parameters, db=db)

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
			return 'http://localhost/fourcat/data/' + query.data["query"].replace("*", "") + '-' + query_key + '.csv'
		else:
			results = results.replace("\\", "/").split("/").pop()
		
		return results

	else:
		return "no_file"

def validateQuery(parameters):
	"""
	Validates the client-side user input

	"""

	if not parameters:
		print('Please provide valid parameters.')
		return -1

	stop_words = get_stop_words('en')

	# TEMPORARY MEASUREMENT
	# Querying can only happen for max two weeks
	#max_daterange = 1209600

	# if parameters["min_date"] == 0 or parameters["max_date"] == 0:
	# 	return "Temporary hardware limitation:\nUse a date range of max. two weeks."

	# Ensure querying can only happen for max two weeks week (temporary measurement)
	# if parameters["min_date"] != 0 and parameters["max_date"] != 0:
	# 	if (parameters["max_date"] - parameters["min_date"]) > max_daterange:
	# 		return "Temporary hardware limitation:\nUse a date range of max. two weeks."

	# Ensure no weird negative timestamps happening
	if parameters["min_date"] < 0 or parameters["max_date"] < 0:
		return "Date(s) set too early."

	# Ensure the min date is not later than the max date
	if parameters["min_date"] != 0 and parameters["max_date"] != 0:
		if parameters["min_date"] >= parameters["max_date"]:
			return "The first date is later than or the same as the second."

	# Ensure the board is correct
	if parameters["board"] not in config.SCRAPE_BOARDS:
		return "Invalid board"

	# Body query should be at least three characters long and should not be just a stopword.
	# 'empty' passes this.
	if len(parameters["body_query"]) < 3:
		return "Body query is too short. Use at least three characters."
	elif parameters["body_query"] in stop_words:
		return "Use a body input that is not a stop word."
	# Query must contain alphanumeric characters
	elif not re.search('[a-zA-Z0-9]', parameters["body_query"]):
		return "Body query must contain alphanumeric characters."

	# Subject query should be at least three characters long and should not be just a stopword.
	# 'empty' passes this.
	if len(parameters["subject_query"]) < 3:
		return "Subject query is too short. Use at least three characters."
	elif parameters["subject_query"] in stop_words:
		return "Use a subject input that is not a stop word."
	# Query must contain alphanumeric characters
	elif not re.search('[a-zA-Z0-9]', parameters["subject_query"]):
		return "Subject query must contain alphanumeric characters."

	# Keyword-dense thread length should be at least thirty.
	if parameters["dense_length"] > 0 and parameters["dense_length"] < 10:
		return "Keyword-dense thread length should be at least ten."
	# Keyword-dense thread density should be at least 15%.
	elif parameters["dense_percentage"] > 0 and parameters["dense_percentage"] < 10:
		return "Keyword-dense thread density should be at least 10%."

	# Check if there are enough parameters provided.
	# Body and subject queryies may be empty if date ranges are max a week apart.
	if parameters["body_query"] == 'empty' and parameters["subject_query"] == 'empty':
		# Check if the date range is less than a week.
		if parameters["min_date"] != 0 and parameters["max_date"] != 0:
			time_diff = parameters["max_date"] - parameters["min_date"]
			print(time_diff)
			if time_diff >= 2419200:
				return "With no text querying, filter on a date range of max four weeks."
		else:
			return "Input either a body or subject query, or filter on a date range of max four weeks."
	
	return True