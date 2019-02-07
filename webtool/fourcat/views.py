import os
import re
import csv
import json
import config
import datetime
import markdown

from flask import render_template, jsonify, abort, request, redirect, send_from_directory
from flask_login import login_required, current_user
from fourcat import app, db, queue, openapi, limiter
from fourcat.helpers import Pagination, string_to_timestamp, load_postprocessors, get_available_postprocessors, get_preview

from backend.lib.query import SearchQuery
from backend.lib.job import Job
from backend.lib.exceptions import JobAlreadyExistsException, JobNotFoundException
from backend.lib.helpers import get_absolute_folder

from stop_words import get_stop_words


@app.template_filter('datetime')
def _jinja2_filter_datetime(date, fmt=None):
	date = datetime.datetime.fromtimestamp(date)
	format = "%d-%m-%Y" if not fmt else fmt
	return date.strftime(format)

@app.template_filter('numberify')
def _jinja2_filter_numberify(number):
	try:
		number = int(number)
	except TypeError:
		return number

	if number > 1000000:
		return str(int(number / 1000000)) + "m"
	elif number > 1000:
		return str(int(number / 1000)) + "k"

	return str(number)

@app.template_filter('markdown')
def _jinja2_filter_markdown(text):
	return markdown.markdown(text)


@app.route('/')
def show_frontpage():
	"""
	Index page: news and introduction

	:return:
	"""

	# load corpus stats that are generated daily, if available
	stats_path = get_absolute_folder(os.path.dirname(__file__)) + "/../../stats.json"
	if os.path.exists(stats_path):
		with open(stats_path) as stats_file:
			stats = stats_file.read()
		try:
			stats = json.loads(stats)
		except json.JSONDecodeError:
			stats = None
	else:
		stats = None

	return render_template("frontpage.html", stats=stats, boards=config.PLATFORMS)


@app.route('/tool/')
@login_required
def show_index():
	"""
	Main tool frontend
	"""
	return render_template('tool.html', boards=config.PLATFORMS)


@app.route('/get-boards/<string:platform>/')
@login_required
def getboards(platform):
	if platform not in config.PLATFORMS or "boards" not in config.PLATFORMS[platform]:
		result = False
	else:
		result = config.PLATFORMS[platform]["boards"]

	return jsonify(result)


@app.route('/page/<string:page>/')
def show_page(page):
	"""
	Display a markdown page within the 4CAT UI

	To make adding static pages easier, they may be saved as markdown files
	in the pages subdirectory, and then called via this view. The markdown
	will be parsed to HTML and displayed within the layout template.

	:param page: ID of the page to load, should correspond to a markdown file
	in the pages/ folder (without the .md extension)
	:return:  Rendered template
	"""
	page = re.sub(r"[^a-zA-Z0-9-_]*", "", page)
	page_class = "page-" + page
	page_folder = os.path.dirname(os.path.abspath(__file__)) + "/pages"
	page_path = page_folder + "/" + page + ".md"

	if not os.path.exists(page_path):
		abort(404)

	with open(page_path) as file:
		page_raw = file.read()
		page_parsed = markdown.markdown(page_raw)
		page_parsed = re.sub(r"<h2>(.*)</h2>", r"<h2><span>\1</span></h2>", page_parsed)

	return render_template("page.html", body_content=page_parsed, body_class=page_class, page_name=page)


@app.route("/queue-query/", methods=["POST"])
@login_required
@limiter.limit("2 per minute")
@openapi.endpoint
def string_query():
	"""
	Queue a 4CAT Query

	Requires authentication by logging in or providing a valid access token.

	:param str platform: Platform ID to query

	:request-param str board:  Board ID to query
	:request-param str platform:  Platform ID to query
	:request-param str body_query:  String to match in the post body
	:request-param str subject_query:  String to match in the post subject
	:request-param str ?full_threads:  Whether to return full thread data: if
	                                   set, return full thread data.
    :request-param int dense_percentage:  Lower threshold for dense threads
    :request-param int dense_length: Minimum length for dense threads matching
    :request-param str ?use_data:  Match within given time period: if set,
                                   match within period.
    :request-param int min_date:  Timestamp marking the beginning of the match
                                  period
    :request-param int max_date:  Timestamp marking the end of the match period
    :request-param str ?access_token:  Access token; only required if not
                                       logged in currently.

	:return str:  The query key, which may be used to later retrieve query
	              status and results.
	"""

	parameters = {
		"board": request.form.get("board", ""),
		"platform": request.form.get("platform", ""),
		"body_query": request.form.get("body_query", ""),
		"subject_query": request.form.get("subject_query", ""),
		"full_thread": (request.form.get("full_threads", "no") != "no"),
		"dense_threads": (request.form.get("dense_threads", "no") != "no"),
		"dense_percentage": int(request.form.get("dense_percentage", 0)),
		"dense_length": int(request.form.get("dense_length", 0)),
		"min_date": string_to_timestamp(request.form.get("min_date", "")) if request.form.get("use_date",
																							  "no") != "no" else 0,
		"max_date": string_to_timestamp(request.form.get("max_date", "")) if request.form.get("use_date",
																							  "no") != "no" else 0,
		"user": current_user.get_id()
	}

	valid = validateQuery(parameters)

	if valid != True:
		return "Invalid query. " + valid

	# Queue query
	query = SearchQuery(parameters=parameters, db=db)

	try:
		queue.add_job(jobtype="%s-search" % parameters["platform"], remote_id=query.key)
	except JobAlreadyExistsException:
		pass

	return query.key


@app.route('/check_query/<query_key>/')
@login_required
@openapi.endpoint
def check_query(query_key):
	"""
	Check query status

	Requires authentication by logging in or providing a valid access token.

	:param str query_key:  ID of the query for which to return the status
	:return: Query status, containing the `status`, `query`, number of `rows`,
	         the query `key`, whether the query is `done`, the `path` of the
	         result file and whether the query result is `empty`.
	"""
	try:
		query = SearchQuery(key=query_key, db=db)
	except TypeError:
		abort(404)

	results = query.check_query_finished()
	if results:
		if app.debug:
			path = 'http://localhost/fourcat/data/' + query.data["query"].replace("*", "") + '-' + query_key + '.csv'
		else:
			path = results.replace("\\", "/").split("/").pop()

		querydata = query.data
		querydata["parameters"] = json.loads(querydata["parameters"])
		preview = render_template("posts-preview.html", query=querydata, preview=get_preview(query))
	else:
		path = ""
		preview = ""

	status = {
		"status": query.get_status(),
		"query": query.data["query"],
		"rows": query.data["num_rows"],
		"key": query_key,
		"done": True if results else False,
		"preview": preview,
		"path": path,
		"empty": query.data["is_empty"]
	}

	return jsonify(status)


@app.route('/result/<string:query_key>/')
@login_required
@openapi.endpoint
def get_result(query_key):
	"""
	Get query result

	:param str query_key:  ID of the query for which to return the result
	:return:  Result file
	:rmime: text/csv
	"""
	try:
		query = SearchQuery(key=query_key, db=db)
	except TypeError:
		abort(404)

	results = query.check_query_finished()
	if not results:
		abort(404)

	return send_from_directory(config.PATH_DATA, results.replace("\\", "/").split("/").pop())


@app.route('/results/', defaults={'page': 1})
@app.route('/results/page/<int:page>/')
@login_required
def show_results(page):
	"""
	Show results overview

	For each result, available analyses are also displayed.

	:return:  Rendered template
	"""
	page_size = 20
	offset = (page - 1) * page_size
	all_results = request.args.get("all_results", False)

	if all_results:
		num_queries = db.fetchone("SELECT COUNT(*) AS num FROM queries WHERE key_parent = ''")["num"]
		queries = db.fetchall("SELECT * FROM queries WHERE key_parent = '' ORDER BY timestamp DESC LIMIT %s OFFSET %s",
							  (page_size, offset))
	else:
		num_queries = \
			db.fetchone("SELECT COUNT(*) AS num FROM queries WHERE key_parent = '' AND parameters::json->>'user' = %s",
						(current_user.get_id(),))["num"]
		queries = db.fetchall(
			"SELECT * FROM queries WHERE key_parent = '' AND parameters::json->>'user' = %s ORDER BY timestamp DESC LIMIT %s OFFSET %s",
			(current_user.get_id(), page_size, offset))

	if not queries and page != 1:
		abort(404)

	pagination = Pagination(page, page_size, num_queries)
	filtered = []
	postprocessors = load_postprocessors()

	for query in queries:
		query["parameters"] = json.loads(query["parameters"])
		query["subqueries"] = []

		subqueries = db.fetchall("SELECT * FROM queries WHERE key_parent = %s ORDER BY timestamp ASC", (query["key"],))
		for subquery in subqueries:
			subquery["parameters"] = json.loads(subquery["parameters"])
			if "type" not in subquery["parameters"] or subquery["parameters"]["type"] not in postprocessors:
				continue
			subquery["postprocessor"] = postprocessors[subquery["parameters"]["type"]]
			query["subqueries"].append(subquery)

		filtered.append(query)

	return render_template("results.html", queries=filtered, pagination=pagination, all_results=all_results)


@app.route('/results/<string:key>/')
@app.route('/results/<string:key>/postprocessors/')
def show_result(key):
	"""
	Show result page

	The page contains query details and a download link, but also shows a list
	of finished and available post-processors.

	:param key:  Result key
	:return:  Rendered template
	"""
	try:
		query = SearchQuery(key=key, db=db)
	except ValueError:
		abort(404)

	# subqueries are not available via a separate page
	if query.data["key_parent"]:
		abort(404)

	# initialize the data we need
	processors = load_postprocessors()
	unfinished_postprocessors = processors.copy()
	is_postprocessor_running = False
	analyses = query.get_analyses(queue)
	filtered_subqueries = analyses["running"].copy()
	querydata = query.data
	querydata["parameters"] = json.loads(querydata["parameters"])

	# for each subquery, determine whether it is finished or running
	# and remove it from the list of available post-processors
	for subquery in analyses["running"]:
		details = json.loads(subquery["parameters"])
		subquery["parameters"] = details
		subquery["postprocessor"] = processors[details["type"]]

		if not subquery["is_finished"]:
			is_postprocessor_running = True

		if details["type"] in unfinished_postprocessors:
			del unfinished_postprocessors[details["type"]]

	# likewise, see if any post-processor jobs were queued (but have not been
	# started yet) and also remove those from the list of available post-
	# processors. additionally, add them as a provisional subquery to show in
	# the UI
	available_postprocessors = unfinished_postprocessors.copy()
	for job in analyses["queued"]:
		if job.data["jobtype"] in unfinished_postprocessors:
			del available_postprocessors[job.data["jobtype"]]
			is_postprocessor_running = True

			if job.data["timestamp_claimed"] == 0:
				filtered_subqueries.append({
					"key": "job%s" % job.data["id"],
					"postprocessor": processors[job.data["jobtype"]],
					"is_finished": False,
					"status": ""
				})

	# show preview
	if query.is_finished() and querydata["num_rows"] > 0:
		preview = get_preview(query)
	else:
		preview = None

	# we can either show this view as a separate page or as a bunch of html
	# to be retrieved via XHR
	standalone = "postprocessors" not in request.url
	template = "result.html" if standalone else "result-details.html"
	return render_template(template, preview=preview, query=querydata, postprocessors=available_postprocessors,
						   subqueries=filtered_subqueries, is_postprocessor_running=is_postprocessor_running)


@app.route('/results/<string:key>/postprocessors/queue/<string:postprocessor>/', methods=["GET", "POST"])
@login_required
def queue_postprocessor(key, postprocessor):
	"""
	Queue a new post-processor

	:param key:  Key of query to queue the post-processor for
	:param postprocessor:  ID of the post-processor to queue
	:return:  Either a redirect, or a JSON status if called asynchronously
	"""
	is_async = request.args.get("async", "no") != "no"

	# cover all bases - can only run postprocessor on "parent" query
	try:
		query = SearchQuery(key=key, db=db)
		if query.data["key_parent"] != "":
			abort(404)
	except TypeError:
		abort(404)

	# check if post-processor is available for this query
	available = get_available_postprocessors(query)
	if postprocessor not in available:
		abort(404)

	# okay, we're good - queue it
	queue.add_job(jobtype=postprocessor, remote_id=query.key, details={"type": postprocessor})

	if is_async:
		return jsonify({"status": "success"})
	else:
		return redirect("/results/" + query.key + "/")


@app.route('/check_postprocessors/')
@login_required
def check_postprocessor():
	try:
		keys = json.loads(request.args.get("subqueries"))
	except (TypeError, json.decoder.JSONDecodeError):
		abort(404)

	subqueries = []

	for key in keys:
		type = "query"
		try:
			if key[0:3] == "job" and len(key) > 3:
				try:
					query = Job.get_by_ID(key[3:], database=db)
					type = "job"
				except (ValueError, JobNotFoundException):
					query = SearchQuery(job=key[3:], db=db)
			else:
				query = SearchQuery(key=key, db=db)
				if query.data["key_parent"] == "":
					continue
		except (TypeError, ValueError) as e:
			print(e)
			continue

		processors = load_postprocessors()

		if type == "query":
			details = json.loads(query.data["parameters"])
			subquery = query.data
			subquery["postprocessor"] = processors[details["type"]]

			subqueries.append({
				"key": query.key,
				"job": details["job"] if "job" in details else "",
				"finished": query.is_finished(),
				"html": render_template("result-subquery.html", subquery=subquery)
			})
		else:
			subquery = {
				"key": "job%s" % query.data["id"],
				"is_finished": False,
				"postprocessor": processors[query.data["jobtype"]],
				"status": ""
			}
			subqueries.append({
				"key": "job%s" % query.data["id"],
				"job": query.data["id"],
				"finished": False,
				"html": render_template("result-subquery.html", subquery=subquery)
			})

	return jsonify(subqueries)


def validateQuery(parameters):
	"""
	Validates the client-side user input

	"""

	if not parameters:
		return "Please provide valid parameters."

	stop_words = get_stop_words('en')

	# TEMPORARY MEASUREMENT
	# Querying can only happen for max two weeks
	# max_daterange = 1209600

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
	if "platform" not in parameters or "board" not in parameters:
		return "Please provide a board to search"

	if parameters["platform"] not in config.PLATFORMS:
		return "Please choose a valid platform to search"

	if parameters["board"] not in config.PLATFORMS[parameters["platform"]]["boards"]:
		return "Please choose a valid board for querying"

	# Keyword-dense thread length should be at least thirty.
	if parameters["dense_length"] > 0 and parameters["dense_length"] < 10:
		return "Keyword-dense thread length should be at least ten."
	# Keyword-dense thread density should be at least 15%.
	elif parameters["dense_percentage"] > 0 and parameters["dense_percentage"] < 10:
		return "Keyword-dense thread density should be at least 10%."

	# Check if there are enough parameters provided.
	# Body and subject queryies may be empty if date ranges are max a week apart.
	if parameters["body_query"] == "" and parameters["subject_query"] == "":
		# Check if the date range is less than a week.
		if parameters["min_date"] != 0 and parameters["max_date"] != 0:
			time_diff = parameters["max_date"] - parameters["min_date"]
			if time_diff >= 2419200:
				return "With no text querying, filter on a date range of max four weeks."
			else:
				return True
		else:
			return "Input either a body or subject query, or filter on a date range of max four weeks."

	# Body query should be at least three characters long and should not be just a stopword.
	if parameters["body_query"] and len(parameters["body_query"]) < 3:
		return "Body query is too short. Use at least three characters."
	elif parameters["body_query"] in stop_words:
		return "Use a body input that is not a stop word."
	# Query must contain alphanumeric characters
	elif parameters["body_query"] and not re.search('[a-zA-Z0-9]', parameters["body_query"]):
		return "Body query must contain alphanumeric characters."

	# Subject query should be at least three characters long and should not be just a stopword.
	if parameters["subject_query"] and len(parameters["subject_query"]) < 3:
		return "Subject query is too short. Use at least three characters."
	elif parameters["subject_query"] in stop_words:
		return "Use a subject input that is not a stop word."
	elif parameters["subject_query"] and not re.search('[a-zA-Z0-9]', parameters["subject_query"]):
		# Query must contain alphanumeric characters
		return "Subject query must contain alphanumeric characters."

	return True
