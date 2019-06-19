"""
4CAT Tool API - To be used to queue and check datasets
"""

import hashlib
import psutil
import config
import json
import time
import csv
import os

from pathlib import Path

import backend

from flask import jsonify, abort, request, render_template, redirect
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from webtool import app, db, log, openapi, limiter, queue
from webtool.views import queue_processor
from webtool.lib.helpers import string_to_timestamp, get_preview, validate_query

from backend.lib.queue import JobQueue
from backend.lib.dataset import DataSet

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
	lockfile = Path(config.PATH_ROOT, config.PATH_LOCKFILE, "4cat.pid")
	if os.path.isfile(lockfile):
		with lockfile.open() as pidfile:
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
def queue_dataset():
	"""
	Queue a 4CAT search query for processing into a dataset

	Requires authentication by logging in or providing a valid access token.

	:request-param str board:  Board ID to query
	:request-param str datasource:  Data source ID to query
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

	:return str:  The dataset key, which may be used to later retrieve dataset
	              status and results.
	"""

	parameters = {
		"board": request.form.get("board", ""),
		"datasource": request.form.get("datasource", ""),
		"body_query": request.form.get("body_query", ""),
		"subject_query": request.form.get("subject_query", ""),
		"full_thread": (request.form.get("full_thread", "no") != "no"),
		"url": (request.form.get("url_query", "")),
		"dense_threads": (request.form.get("dense_threads", "no") != "no"),
		"dense_percentage": int(request.form.get("dense_percentage", 0)),
		"dense_length": int(request.form.get("dense_length", 0)),
		"country_flag": request.form.get("country_flag", "all") if request.form.get("country_check",
																					"no") != "no" else "all",
		"dense_country_percentage": int(request.form.get("dense_country_percentage", 0)) if request.form.get(
			"check_dense_country",
			"no") != "no" else 0,
		"random_amount": int(request.form.get("random_amount", 0)) if request.form.get("random_sample",
																					   "no") != "no" else False,
		"min_date": string_to_timestamp(request.form.get("min_date", "")) if request.form.get("use_date",
																							  "no") != "no" else 0,
		"max_date": string_to_timestamp(request.form.get("max_date", "")) if request.form.get("use_date",
																							  "no") != "no" else 0,
		"user": current_user.get_id()
	}

	valid = validate_query(parameters)

	if valid != True:
		return "Invalid query. " + valid

	# Queue dataset
	dataset = DataSet(parameters=parameters, db=db)

	queue.add_job(jobtype="%s-search" % parameters["datasource"], remote_id=dataset.key)

	return dataset.key


@app.route('/api/check-query/')
@login_required
@openapi.endpoint
def check_dataset():
	"""
	Check dataset status

	Requires authentication by logging in or providing a valid access token.

	:request-param str query_key:  ID of the dataset for which to return the status
	:return: Dataset status, containing the `status`, `query`, number of `rows`,
	         the dataset `key`, whether the dataset is `done`, the `path` of the
	         result file and whether the dataset is `empty`.
	"""
	dataset_key = request.args.get("key")
	try:
		dataset = DataSet(key=dataset_key, db=db)
	except TypeError:
		return jsonify({"error": "Not a valid dataset key."})

	results = dataset.check_dataset_finished()
	if results == 'empty':
		dataset_data = dataset.data
		dataset_data["parameters"] = json.loads(dataset_data["parameters"])
		path = False
		preview = ""
	elif results:
		# Return absolute folder when using localhost for debugging
		path = results.name
		dataset_data = dataset.data
		dataset_data["parameters"] = json.loads(dataset_data["parameters"])
		preview = render_template("posts-preview.html", query=dataset_data, preview=get_preview(dataset))
	else:
		path = ""
		preview = ""

	status = {
		"status": dataset.get_status(),
		"query": dataset.data["query"],
		"rows": dataset.data["num_rows"],
		"key": dataset_key,
		"done": True if results else False,
		"preview": preview,
		"path": path,
		"empty": (dataset.data["num_rows"] == 0)
	}

	return jsonify(status)


@app.route("/api/delete-query/", methods=["DELETE", "POST"])
@api_ratelimit
@login_required
@openapi.endpoint
def delete_dataset():
	"""
	Delete a dataset

	Only available to administrators. Deletes a dataset, as well as any
	children linked to it, from 4CAT. Calling this on a dataset that is
	currently being executed is undefined behaviour.

	:request-param str query_key:  ID of the dataset for which to return the status
    :request-param str ?access_token:  Access token; only required if not
                                       logged in currently.

	:return: A dictionary with either an `error` or a successful `status`.
	"""
	if not current_user.is_admin():
		return jsonify({"error": "Not allowed"})

	dataset_key = request.form.get("key")
	try:
		dataset = DataSet(key=dataset_key, db=db)
	except TypeError:
		return jsonify({"error": "Not a valid dataset key."})

	dataset.delete()
	return jsonify({"status": "success"})


@app.route("/api/check-queue/")
@api_ratelimit
@login_required
@openapi.endpoint
def check_queue():
	"""
	Get the amount of datasets yet to finish processing

	:return: An JSON object with one item `count` containing the number of
	queued or active datasets.
	"""
	unfinished_datasets = db.fetchone("SELECT COUNT(*) AS count FROM jobs WHERE jobtype LIKE '%-search'")

	return jsonify(unfinished_datasets)


@app.route("/api/queue-processor/", methods=["POST"])
@api_ratelimit
@login_required
@openapi.endpoint
def queue_processor_api():
	"""
	Queue a new processor

	Queues the processor for a given dataset; with the returned query key,
	the processor status can then be checked periodically to download the
	result when available.

	Note that apart from the required parameters, further parameters may be
	provided based on the configuration options available for the chosen
	processor. Available options may be found via the
	`/get-available-processors/` endpoint.

	:request-param str key:  Key of dataset to queue processor for
	:request-param str processor:  ID of processor to queue
    :request-param str ?access_token:  Access token; only required if not
                                       logged in currently.

	:return: A list of dataset properties, with each dataset an item with a `key`,
	        whether it had `finished`, a `html` snippet containing details,
	        a `url` at which the result may be downloaded when finished, and a
	        list of `messages` describing any warnings generated while queuing.
	"""
	if request.files and "input_file" in request.files:
		input_file = request.files["input_file"]
		if not input_file:
			return jsonify({"error": "No file input provided"})

		if input_file.filename[-4:] != ".csv":
			return jsonify({"error": "File input is not a csv file"})

		test_csv_file = csv.DictReader(input_file.stream)
		if "body" not in test_csv_file.fieldnames:
			return jsonify({"error": "File must contain a 'body' column"})

		filename = secure_filename(input_file.filename)
		input_file.save(config.PATH_DATA + "/")

	else:
		key = request.form.get("key", "")

	return queue_processor(key, request.form.get("processor", ""), is_async=True)


@app.route("/api/get-available-processors/")
@login_required
@api_ratelimit
@openapi.endpoint
def available_processors():
	"""
	Get processors available for a dataset

	:request-param string key:  Dataset key to get processors for
	:return: An object containing the `error` if the request failed, or a list
	         of processors, each with a `name`, a `type` ID, a
	         `description` of what it does, the `extension` of the file it
	         produces, a `category` name, what types of datasets it `accepts`,
	         and a list of `options`, if applicable.
	"""
	try:
		dataset = DataSet(key=request.args.get("key"), db=db)
	except TypeError:
		return jsonify({"error": "Not a valid dataset key."})

	return jsonify(dataset.get_available_processors())


@app.route('/api/check-processors/')
@login_required
@openapi.endpoint
def check_processor():
	"""
	Check processor status

	:request-param str subqueries:  A JSON-encoded list of dataset keys to get
	                                the status of
	:return: A list of dataset data, with each dataset an item with a `key`,
	        whether it had `finished`, a `html` snippet containing details, and
	        a `url` at which the result may be downloaded when finished.
	         `finished`, `html` and `result_path`.
	"""
	try:
		keys = json.loads(request.args.get("subqueries"))
	except (TypeError, json.decoder.JSONDecodeError):
		return jsonify({"error": "Unexpected format for child dataset key list."})

	children = []

	for key in keys:
		try:
			dataset = DataSet(key=key, db=db)
		except TypeError:
			continue

		children.append({
			"key": dataset.key,
			"finished": dataset.is_finished(),
			"html": render_template("result-child.html", child=dataset, dataset=dataset.get_genealogy()[-2], query=dataset.get_genealogy()[0],
									processors=backend.all_modules.processors),
			"url": "/result/" + dataset.data["result_file"]
		})

	return jsonify(children)


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
