"""
4CAT Tool API - To be used to queue and check datasets
"""

import importlib
import hashlib
import psutil
import config
import json
import time
import csv
import os
import re

from pathlib import Path

import backend

from flask import jsonify, request, render_template, render_template_string, redirect, send_file, url_for, flash, \
	get_flashed_messages
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from webtool import app, db, log, openapi, limiter, queue
from webtool.lib.helpers import get_preview, error

from backend.lib.exceptions import QueryParametersException
from backend.lib.queue import JobQueue
from backend.lib.job import Job
from backend.lib.dataset import DataSet
from backend.lib.helpers import UserInput, call_api

api_ratelimit = limiter.shared_limit("3 per second", scope="api")

API_SUCCESS = 200
API_FAIL = 404


@app.route("/api/")
@api_ratelimit
def openapi_overview():
	return jsonify({
		"status": "The following API specifications are available from this server.",
		"data": {
			api_id: "http" + (
				"s" if config.FlaskConfig.SERVER_HTTPS else "") + "://" + config.FlaskConfig.SERVER_NAME + "/api/spec/" + api_id + "/"
			for api_id in openapi.apis
		}
	})


@app.route('/api/spec/<string:api_id>/')
@api_ratelimit
def openapi_specification(api_id="all"):
	"""
	Show OpenAPI specification of 4CAT API

	:return: OpenAPI-formatted API specification
	"""
	return jsonify(openapi.generate(api_id))


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


@app.route("/api/datasource-form/<string:datasource_id>/")
@login_required
def datasource_form(datasource_id):
	"""
	Get data source query form HTML

	The data source needs to have been loaded as a module with a
	`ModuleCollector`, and also needs to be present in `config.py`. If so, this
	endpoint returns the HTML form configured by the template in the
	data source's folder, or a default tool template if that one is not
	available.

	If a file `tool.js` is available in the data source's `webtool` folder, the
	response will indicate that a javascript file is available for this data
	source.

	:param datasource_id:  Data source ID, as specified in the data source and
						   config.py
	:return: A JSON object with the `html` of the template,
	         a boolean `javascript` determining whether javascript should be
	         loaded for this template, a `status` code and the `datasource` ID.

	:return-error 404: If the datasource does not exist.
	"""
	if datasource_id not in backend.all_modules.datasources:
		return error(404, message="Datasource '%s' does not exist" % datasource_id)

	if datasource_id not in config.DATASOURCES:
		return error(404, message="Datasource '%s' does not exist" % datasource_id)

	datasource = backend.all_modules.datasources[datasource_id]
	template_path = datasource["path"].joinpath("webtool", "query-form.html")

	if not template_path.exists():
		template_path = Path("tool_default.html")

	javascript_path = datasource["path"].joinpath("webtool", "tool.js")
	has_javascript = javascript_path.exists()

	if not template_path.exists():
		return error(404, message="No interface exists for datasource '%s'" % datasource_id)

	html = render_template_string(template_path.read_text(), datasource_id=datasource_id,
								  datasource_config=config.DATASOURCES[datasource_id], datasource=datasource)

	return jsonify({"status": "success", "datasource": datasource_id, "has_javascript": has_javascript, "html": html})


@app.route("/api/datasource-script/<string:datasource_id>/")
@login_required
def datasource_script(datasource_id):
	"""
	Get data source query form HTML

	The data source needs to have been loaded as a module with a
	`ModuleCollector`, and also needs to be present in `config.py`. If so, this
	endpoint returns the data source's tool javascript file, if it exists as
	`tool.js` in the data source's `webtool` folder.

	:param datasource_id:  Datasource ID, as specified in the datasource and
						   config.py
	:return: A javascript file
	:return-error 404: If the datasource does not exist.
	"""
	if datasource_id not in backend.all_modules.datasources:
		return error(404, message="Datasource '%s' does not exist" % datasource_id)

	if datasource_id not in config.DATASOURCES:
		return error(404, message="Datasource '%s' does not exist" % datasource_id)

	datasource = backend.all_modules.datasources[datasource_id]
	script_path = datasource["path"].joinpath("webtool", "tool.js")

	if not script_path.exists():
		return error(404, message="Datasource '%s' does not exist" % datasource_id)

	return send_file(str(script_path))


@app.route("/api/queue-query/", methods=["POST"])
@login_required
@limiter.limit("5 per minute")
@openapi.endpoint("tool")
def queue_dataset():
	"""
	Queue a 4CAT search query for processing into a dataset

	Requires authentication by logging in or providing a valid access token.
	Request parameters vary by data source. The ones mandated constitute the
	minimum but more may be required.

	:request-param str board:  Board ID to query
	:request-param str datasource:  Data source ID to query
	:request-param str body_match:  String to match in the post body
	:request-param str subject_match:  String to match in the post subject
    :request-param int min_date:  Timestamp marking the beginning of the match
                                  period
    :request-param int max_date:  Timestamp marking the end of the match period
    :request-param str ?access_token:  Access token; only required if not
                                       logged in currently.

	:return str:  The dataset key, which may be used to later retrieve dataset
	              status and results.
	:return-error 404: If the datasource does not exist.
	"""

	datasource_id = request.form.get("datasource", "")
	if datasource_id not in backend.all_modules.datasources:
		return error(404, message="Datasource '%s' does not exist" % datasource_id)

	search_worker_id = datasource_id + "-search"
	if search_worker_id not in backend.all_modules.workers:
		return error(404, message="Datasource '%s' has no search interface" % datasource_id)

	search_worker = backend.all_modules.workers[search_worker_id]
	worker_class = backend.all_modules.load_worker_class(search_worker)

	if hasattr(worker_class, "validate_query"):
		try:
			sanitised_query = worker_class.validate_query(request.form.to_dict(), request, current_user)
		except QueryParametersException as e:
			return "Invalid query. %s" % e
	else:
		sanitised_query = request.form.to_dict()

	sanitised_query["user"] = current_user.get_id()
	sanitised_query["datasource"] = datasource_id
	sanitised_query["type"] = search_worker_id

	sanitised_query["pseudonymise"] = bool(request.form.to_dict().get("pseudonymise", False))

	dataset = DataSet(parameters=sanitised_query, db=db, type=search_worker_id)

	if hasattr(worker_class, "after_create"):
		worker_class.after_create(sanitised_query, dataset, request)

	queue.add_job(jobtype=search_worker_id, remote_id=dataset.key)

	return dataset.key


@app.route('/api/check-query/')
@login_required
@openapi.endpoint("tool")
def check_dataset():
	"""
	Check dataset status

	Requires authentication by logging in or providing a valid access token.

	:request-param str key:  ID of the dataset for which to return the status
	:return: Dataset status, containing the `status`, `query`, number of `rows`,
	         the dataset `key`, whether the dataset is `done`, the `path` of the
	         result file and whether the dataset is `empty`.

	:return-schema: {
		type=object,
		properties={
			status={type=string},
			query={type=string},
			rows={type=integer},
			key={type=string},
			done={type=boolean},
			path={type=string},
			empty={type=boolean},
			is_favourite={type=boolean}
		}
	}

	:return-error 404:  If the dataset does not exist.
	"""
	dataset_key = request.args.get("key")
	try:
		dataset = DataSet(key=dataset_key, db=db)
	except TypeError:
		return error(404, error="Dataset does not exist.")

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
		"status_html": render_template("result-status.html", dataset=dataset),
		"label": dataset.get_label(),
		"query": dataset.data["query"],
		"rows": dataset.data["num_rows"],
		"key": dataset_key,
		"done": True if dataset.is_finished() else False,
		"preview": preview,
		"path": path,
		"empty": (dataset.data["num_rows"] == 0),
		"is_favourite": (db.fetchone("SELECT COUNT(*) AS num FROM users_favourites WHERE name = %s AND key = %s",
									 (current_user.get_id(), dataset.key))["num"] > 0)
	}

	return jsonify(status)


@app.route("/api/delete-query/", methods=["DELETE", "POST"])
@api_ratelimit
@login_required
@openapi.endpoint("tool")
def delete_dataset(key=None):
	"""
	Delete a dataset

	Only available to administrators. Deletes a dataset, as well as any
	children linked to it, from 4CAT. Calling this on a dataset that is
	currently being executed is undefined behaviour.

	:request-param str query_key:  ID of the dataset for which to return the status
    :request-param str ?access_token:  Access token; only required if not
                                       logged in currently.

	:return: A dictionary with a successful `status`.

	:return-schema: {type=object,properties={status={type=string}}}

	:return-error 404:  If the dataset does not exist.
	"""
	if not current_user.is_admin():
		return error(403, message="Not allowed")

	dataset_key = request.form.get("key", "") if not key else key

	try:
		dataset = DataSet(key=dataset_key, db=db)
	except TypeError:
		return error(404, error="Dataset does not exist.")

	dataset.delete()
	return jsonify({"status": "success"})


@app.route("/api/check-search-queue/")
@login_required
@openapi.endpoint("tool")
def check_search_queue():
	"""
	Get the amount of search query datasets yet to finish processing.

	:return: An JSON array with search jobtypes and their counts.

	:return-schema: {type=array,properties={jobtype={type=string}, count={type=integer}},items={type=string}}
	"""
	unfinished_datasets = db.fetchall("SELECT jobtype, COUNT(*)count FROM jobs WHERE jobtype LIKE '%-search' GROUP BY jobtype ORDER BY count DESC;")

	return jsonify(unfinished_datasets)

@app.route("/api/toggle-dataset-favourite/<string:key>")
@login_required
@openapi.endpoint("tool")
def toggle_favourite(key):
	"""
	'Like' a dataset

	Marks the dataset as being liked by the currently active user, which can be
	used for organisation in the front-end.

	:param str key: Key of the dataset to mark as favourite.

	:return: A JSON object with the status of the request
	:return-schema: {type=object,properties={success={type=boolean},favourite_status={type=boolean}}}

	:return-error 404:  If the dataset key was not found
	"""
	try:
		dataset = DataSet(key=key, db=db)
	except TypeError:
		return error(404, error="Dataset does not exist.")

	current_status = db.fetchone("SELECT * FROM users_favourites WHERE name = %s AND key = %s",
								 (current_user.get_id(), dataset.key))
	if not current_status:
		db.insert("users_favourites", data={"name": current_user.get_id(), "key": dataset.key})
		return jsonify({"success": True, "favourite_status": True})
	else:
		db.delete("users_favourites", where={"name": current_user.get_id(), "key": dataset.key})
		return jsonify({"success": True, "favourite_status": False})


@app.route("/api/queue-processor/", methods=["POST"])
@api_ratelimit
@login_required
@openapi.endpoint("tool")
def queue_processor(key=None, processor=None):
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

	:return-schema: {type=object,additionalProperties={type=object,properties={
		key={type=string},
		finished={type=boolean},
		html={type=string},
		url={type=string},
		messages={type=array,items={type=string}}
	}}}
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

	elif not key:
		key = request.form.get("key", "")

	if not processor:
		processor = request.form.get("processor", "")

	# cover all bases - can only run processor on "parent" dataset
	try:
		dataset = DataSet(key=key, db=db)
	except TypeError:
		return jsonify({"error": "Not a valid dataset key."})

	# check if processor is available for this dataset
	if processor not in dataset.processors:
		return jsonify({"error": "This processor is not available for this dataset or has already been run."})

	# create a dataset now
	options = {}
	for option in dataset.processors[processor]["options"]:
		settings = dataset.processors[processor]["options"][option]
		choice = request.values.get("option-" + option, None)
		options[option] = UserInput.parse(settings, choice)

	options["user"] = current_user.get_id()

	analysis = DataSet(parent=dataset.key, parameters=options, db=db,
					   extension=dataset.processors[processor]["extension"], type=processor)
	if analysis.is_new:
		# analysis has not been run or queued before - queue a job to run it
		queue.add_job(jobtype=processor, remote_id=analysis.key)
		job = Job.get_by_remote_ID(analysis.key, database=db)
		analysis.link_job(job)
		analysis.update_status("Queued")
	else:
		flash("This analysis (%s) is currently queued or has already been run with these parameters." %
			  dataset.processors[processor]["name"])

	return jsonify({
		"status": "success",
		"container": "*[data-dataset-key=" + dataset.key + "]",
		"key": analysis.key,
		"html": render_template("result-child.html", child=analysis, dataset=dataset, parent_key=dataset.key,
								processors=backend.all_modules.processors) if analysis.is_new else "",
		"messages": get_flashed_messages(),
		"is_filter": dataset.processors[processor]["is_filter"]
	})


@app.route("/api/get-available-processors/")
@login_required
@api_ratelimit
@openapi.endpoint("tool")
def available_processors():
	"""
	Get processors available for a dataset

	:request-param string key:  Dataset key to get processors for
	:return: An object containing the `error` if the request failed, or a list
	         of processors, each with a `name`, a `type` ID, a
	         `description` of what it does, the `extension` of the file it
	         produces, a `category` name, what types of datasets it `accepts`,
	         and a list of `options`, if applicable.

	:return-schema: {type=array,items={type=object,properties={
		name={type=string},
		type={type=string},
		description={type=string},
		extension={type=string},
		category={type=string},
		accepts={type=array,items={type=string}}
	}}}

	:return-error 404:  If the dataset does not exist.
	"""
	try:
		dataset = DataSet(key=request.args.get("key"), db=db)
	except TypeError:
		return error(404, error="Dataset does not exist.")

	# Class type is not JSON serialisable
	processors = dataset.get_available_processors()
	for key, value in processors.items():
		if "class" in value:
			del value["class"]

	return jsonify(processors)


@app.route('/api/check-processors/')
@login_required
@openapi.endpoint("tool")
def check_processor():
	"""
	Check processor status

	:request-param str subqueries:  A JSON-encoded list of dataset keys to get
	                                the status of
	:return: A list of dataset data, with each dataset an item with a `key`,
	        whether it had `finished`, a `html` snippet containing details, and
	        a `url` at which the result may be downloaded when finished.

	:return-schema:{type=array,items={type=object,properties={
		key={type=string},
		finished={type=boolean},
		html={type=string},
		url={type=string}
	}}}

	:return-error 406:  If the list of subqueries could not be parsed.
	"""
	try:
		keys = json.loads(request.args.get("subqueries"))
	except (TypeError, json.decoder.JSONDecodeError):
		return error(406, error="Unexpected format for child dataset key list.")

	children = []

	for key in keys:
		try:
			dataset = DataSet(key=key, db=db)
		except TypeError:
			continue

		genealogy = dataset.get_genealogy()
		parent = genealogy[-2]
		top_parent = genealogy[0]

		children.append({
			"key": dataset.key,
			"finished": dataset.is_finished(),
			"html": render_template("result-child.html", child=dataset, dataset=parent,
									query=dataset.get_genealogy()[0], parent_key=top_parent.key,
									processors=backend.all_modules.processors),
			"resultrow_html": render_template("result-result-row.html", dataset=top_parent),
			"url": "/result/" + dataset.data["result_file"]
		})

	return jsonify(children)


@app.route("/api/datasource-call/<string:datasource>/<string:action>/", methods=["GET", "POST"])
@login_required
@openapi.endpoint("tool")
def datasource_call(datasource, action):
	"""
	Call datasource function

	Datasources may define custom API calls as functions in a file
	'webtool/views.py'. These are then available as 'actions' with this API
	endpoint. Any GET parameters are passed as keyword arguments to the
	function.

	:param str action:  Action to call
	:return:  A JSON object
	"""
	# allow prettier URLs
	action = action.replace("-", "_")

	if datasource not in backend.all_modules.datasources:
		return error(404, error="Datasource not found.")

	forbidden_call_name = re.compile(r"[^a-zA-Z0-9_]")
	if forbidden_call_name.findall(action) or action[0:2] == "__":
		return error(406, error="Datasource '%s' has no call '%s'" % (datasource, action))

	folder = backend.all_modules.datasources[datasource]["path"]
	views_file = folder.joinpath("webtool", "views.py")
	if not views_file.exists():
		return error(406, error="Datasource '%s' has no call '%s'" % (datasource, action))

	datasource_id = backend.all_modules.datasources[datasource]["id"]
	datasource_calls = importlib.import_module("datasources.%s.webtool.views" % datasource_id)

	if not hasattr(datasource_calls, action) or not callable(getattr(datasource_calls, action)):
		return error(406, error="Datasource '%s' has no call '%s'" % (datasource, action))

	parameters = request.args if request.method == "GET" else request.form
	response = getattr(datasource_calls, action).__call__(request, current_user, **parameters)

	if not response:
		return jsonify({"success": False})
	elif response is True:
		return jsonify({"success": True})
	else:
		return jsonify({"success": True, "data": response})


@app.route("/api/request-token/")
@login_required
@openapi.endpoint("tool")
def request_token():
	"""
	Request an access token

	Requires that the user is currently logged in to 4CAT.

	:return: An object with one item `token`

	:return-schema={type=object,properties={token={type=string}}}

	:return-error 403:  If the user is logged in with an anonymous account.
	"""
	if current_user.get_id() == "autologin":
		# access tokens are only for 'real' users so we can keep track of who
		# (ab)uses them
		return error(403, error="Anonymous users may not request access tokens.")

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
