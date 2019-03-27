"""
4CAT Tool API - To be used to queue and check queries
"""

import hashlib
import psutil
import config
import json
import time
import os

from flask import jsonify, abort, request, render_template, redirect, url_for
from flask_login import login_required, current_user

from webtool import app, db, log, openapi, limiter, queue
from webtool.views import queue_postprocessor
from webtool.lib.helpers import string_to_timestamp, get_preview, validate_query

from backend.lib.queue import JobQueue
from backend.lib.query import DataSet
from backend.lib.helpers import get_absolute_folder, load_postprocessors

api_ratelimit = limiter.shared_limit("1 per second", scope="api")

API_SUCCESS = 200
API_FAIL = 404


@app.route('/api/')
@api_ratelimit
@openapi.endpoint
def openapi_specification():
	"""
	Show OpenAPI specification of 4CAT API

	:return: OpenAPI-formatted API specification
	"""
	return jsonify(openapi.generate())


@app.route('/api/status.json')
@api_ratelimit
def api_status():
	"""
	Get service status

	:return: Flask JSON response
	"""

	# get job stats
	queue = JobQueue(logger=log, database=db)
	jobs = queue.get_all_jobs()
	jobs_count = len(jobs)
	jobs_types = set([job.data["jobtype"] for job in jobs])
	jobs_sorted = {jobtype: len([job for job in jobs if job.data["jobtype"] == jobtype]) for jobtype in jobs_types}
	jobs_sorted["total"] = jobs_count

	# determine if backend is live by checking if the process is running
	lockfile = get_absolute_folder(config.PATH_LOCKFILE) + "/4cat.pid"
	if os.path.isfile(lockfile):
		with open(lockfile) as pidfile:
			pid = pidfile.read()
			backend_live = int(pid) in psutil.pids()
	else:
		backend_live = False

	response = {
		"code": API_SUCCESS,
		"items": {
			"backend": {
				"live": backend_live,
				"queued": jobs_sorted
			},
			"frontend": {
				"live": True  # duh
			}
		}
	}

	return jsonify(response)


@app.route("/api/queue-query/", methods=["POST"])
@login_required
@limiter.limit("5 per minute")
@openapi.endpoint
def queue_query():
	"""
	Queue a 4CAT Query

	Requires authentication by logging in or providing a valid access token.

	:param str platform: Platform ID to query

	:request-param str board:  Board ID to query
	:request-param str platform:  Platform ID to query
	:request-param str body_query:  String to match in the post body
	:request-param str subject_query:  String to match in the post subject
	:request-param str ?full_thread:  Whether to return full thread data: if
	                                   set, return full thread data.
    :request-param int dense_percentage:  Lower threshold for dense threads
    :request-param int dense_length: Minimum length for dense threads matching
    :request-param str ?random_sample:  Whether to return a random sample: if
                                   set, return random posts.
    :request-param int random_amount:  The amount of random posts to return.
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
		"full_thread": (request.form.get("full_thread", "no") != "no"),
		"dense_threads": (request.form.get("dense_threads", "no") != "no"),
		"dense_percentage": int(request.form.get("dense_percentage", 0)),
		"dense_length": int(request.form.get("dense_length", 0)),
		"country_flag": request.form.get("country_flag", "all"),
		"dense_country_percentage": int(request.form.get("dense_country_percentage", 0)) if request.form.get("check_dense_country",
																							  "no") != "no" else False,
		"random_amount": int(request.form.get("random_amount", 0)) if request.form.get("random_sample",
																							  "no") != "no" else False,
		"min_date": string_to_timestamp(request.form.get("min_date", "")) if request.form.get("use_date",
																							  "no") != "no" else 0,
		"max_date": string_to_timestamp(request.form.get("max_date", "")) if request.form.get("use_date",
																							  "no") != "no" else 0,
		"user": current_user.get_id()
	}

	valid = validate_query(parameters)

	if not valid:
		return "Invalid query."

	# Queue query
	query = DataSet(parameters=parameters, db=db)

	queue.add_job(jobtype="%s-search" % parameters["platform"], remote_id=query.key)

	return query.key

@app.route('/api/check-query/')
@login_required
@openapi.endpoint
def check_query():
	"""
	Check query status

	Requires authentication by logging in or providing a valid access token.

	:request-param str query_key:  ID of the query for which to return the status
	:return: Query status, containing the `status`, `query`, number of `rows`,
	         the query `key`, whether the query is `done`, the `path` of the
	         result file and whether the query result is `empty`.
	"""
	query_key = request.args.get("key")
	try:
		query = DataSet(key=query_key, db=db)
	except TypeError:
		return jsonify({"error": "Not a valid query key."})

	results = query.check_query_finished()
	if results == 'empty':
		querydata = query.data
		querydata["parameters"] = json.loads(querydata["parameters"])
		path = False
		preview = ""
	elif results:
		# Return absolute folder when using localhost for debugging
		if app.debug:
			path = 'http://localhost/fourcat/data/' + query.data["result_file"] + '.csv'
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
		"empty": (query.data["num_rows"] == 0)
	}

	return jsonify(status)


@app.route("/api/queue-postprocessor/", methods=["POST"])
@api_ratelimit
@login_required
@openapi.endpoint
def queue_postprocessor_api():
	"""
	Queue a new post-processor

	Queues the post-processor for a given query; with the returned query key,
	the post-processor status can then be checked periodically to download the
	result when available.

	Note that apart from the required parameters, further parameters may be
	provided based on the configuration options available for the chosen
	post-processor. Available options may be found via the
	`/get-available-postprocessors/` endpoint.

	:request-param str key:  Key of query to queue post-processor for
	:request-param str postprocessor:  ID of post-processor to queue
    :request-param str ?access_token:  Access token; only required if not
                                       logged in currently.

	:return: A list of query data, with each query an item with a `key`,
	        whether it had `finished`, a `html` snippet containing details,
	        a `url` at which the result may be downloaded when finished, and a
	        list of `messages` describing any warnings generated while queuing.
	"""
	key = request.form.get("key", "")
	return queue_postprocessor(key, request.form.get("postprocessor", ""), is_async=True)


@app.route("/api/get-available-postprocessors/")
@login_required
@api_ratelimit
@openapi.endpoint
def available_postprocessors():
	"""
	Get post-processors available for a query

	:request-param string key:  Query key to get post-processors for
	:return: An object containing the `error` if the request failed, or a list
	         of post-processors, each with a `name`, a `type` ID, a
	         `description` of what it does, the `extension` of the file it
	         produces, a `category` name, what types of queries it `accepts`,
	         and a list of `options`, if applicable.
	"""
	try:
		query = DataSet(key=request.args.get("key"), db=db)
	except TypeError:
		return jsonify({"error": "Not a valid query key."})

	return jsonify(query.get_available_postprocessors())


@app.route('/api/check-postprocessors/')
@login_required
@openapi.endpoint
def check_postprocessor():
	"""
	Check post-processor status

	:request-param str subqueries:  A JSON-encoded list of query keys to get
	                                the status of
	:return: A list of query data, with each query an item with a `key`,
	        whether it had `finished`, a `html` snippet containing details, and
	        a `url` at which the result may be downloaded when finished.
	         `finished`, `html` and `result_path`.
	"""
	try:
		keys = json.loads(request.args.get("subqueries"))
	except (TypeError, json.decoder.JSONDecodeError):
		return jsonify({"error": "Unexpected format for subquery key list.f"})

	subqueries = []

	for key in keys:
		try:
			query = DataSet(key=key, db=db)
		except TypeError:
			continue

		subqueries.append({
			"key": query.key,
			"finished": query.is_finished(),
			"html": render_template("result-subquery-extended.html", subquery=query, query=query.get_genealogy()[0],
									postprocessors=load_postprocessors()),
			"url": "/result/" + query.data["result_file"]
		})

	return jsonify(subqueries)


@app.route("/api/request-token/")
@login_required
@openapi.endpoint
def request_token():
	"""
	Request an access token

	Requires that the user is currently logged in to 4CAT.

	:return: An object with one item `token`
	"""
	if current_user.get_id() == "autologin":
		# access tokens are only for 'real' users so we can keep track of who
		# (ab)uses them
		abort(403)

	token = db.fetchone("SELECT * FROM access_tokens WHERE name = %s AND (expires = 0 OR expires > %s)",
						(current_user.get_id(), int(time.time())))

	if token:
		token = token["token"]
	else:
		token = current_user.get_id() + str(time.time())
		token = hashlib.sha256(token.encode("utf8")).hexdigest()
		token = {
			"name": current_user.get_id(),
			"token": token,
			"expires": int(time.time()) + (365 * 86400)
		}

		# delete any expired tokens
		db.delete("access_tokens", where={"name": current_user.get_id()})

		# save new token
		db.insert("access_tokens", token)

	if request.args.get("forward"):
		# show HTML page
		return redirect(url_for("show_access_tokens"))
	else:
		# show JSON response (by default)
		return jsonify(token)
