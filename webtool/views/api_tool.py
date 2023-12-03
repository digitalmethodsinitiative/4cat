"""
4CAT Tool API - To be used to queue and check datasets
"""
import itertools
import hashlib
import psutil
import json
import time
import csv
import os

from pathlib import Path

import backend

from flask import jsonify, request, render_template, render_template_string, redirect, send_file, url_for, flash, \
	get_flashed_messages, send_from_directory
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from webtool import app, db, log, openapi, limiter, queue, config
from webtool.lib.helpers import error, setting_required

from common.lib.exceptions import QueryParametersException, JobNotFoundException, \
	QueryNeedsExplicitConfirmationException, QueryNeedsFurtherInputException, DataSetException
from common.lib.queue import JobQueue
from common.lib.job import Job
from common.config_manager import ConfigWrapper
from common.lib.dataset import DataSet
from common.lib.helpers import UserInput, call_api, get_software_version
from common.lib.user import User
from backend.lib.worker import BasicWorker

api_ratelimit = limiter.shared_limit("3 per second", scope="api")
config = ConfigWrapper(config, user=current_user, request=request)

API_SUCCESS = 200
API_FAIL = 404

csv.field_size_limit(1024 * 1024 * 1024)

@app.route("/api/")
@api_ratelimit
def openapi_overview():
	return jsonify({
		"status": "The following API specifications are available from this server.",
		"data": {
			api_id: "http" + (
				"s" if config.get("flask.https") else "") + "://" + config.get("flask.server_name") + "/api/spec/" + api_id + "/swagger.json"
			for api_id in openapi.apis
		}
	})


@app.route('/api/spec/<string:api_id>/')
@app.route('/api/spec/<string:api_id>/swagger.json')
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
	lockfile = Path(config.get('PATH_ROOT'), config.get('PATH_LOCKFILE'), "4cat.pid")
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
@setting_required("privileges.can_create_dataset")
def datasource_form(datasource_id):
	"""
	Get data source query form HTML

	The data source needs to have been loaded as a module with a
	`ModuleCollector`, and also needs to be present in `config.py`. If so, this
	endpoint returns the HTML form configured by the template in the
	data source's folder.

	If a file `tool.js` is available in the data source's `webtool` folder, the
	response will indicate that a javascript file is available for this data
	source.

	If the data source has no search worker or its search worker does not have
	any parameters defined, this returns a 404 Not Found status.

	:param datasource_id:  Data source ID, as specified in the data source and
						   config.py
	:return: A JSON object with the `html` of the template, a `status` code and
	the `datasource` ID.

	:return-error 404: If the datasource does not exist.
	"""
	if datasource_id not in backend.all_modules.datasources:
		return error(404, message="Datasource '%s' does not exist" % datasource_id)

	if datasource_id not in config.get('datasources.enabled'):
		return error(404, message="Datasource '%s' does not exist" % datasource_id)

	datasource = backend.all_modules.datasources[datasource_id]
	worker_class = backend.all_modules.workers.get(datasource_id + "-search")

	if not worker_class:
		return error(404, message="Datasource '%s' has no search worker" % datasource_id)

	worker_options = worker_class.get_options(None, current_user)
	if not worker_options:
		return error(404, message="Datasource '%s' has no dataset parameter options defined" % datasource_id)

	# Status labels to display in query form
	labels = []
	is_local = "local" if hasattr(worker_class, "is_local") and worker_class.is_local else "external"
	is_static = True if hasattr(worker_class, "is_static") and worker_class.is_static else False

	labels.append(is_local)
	if is_static:
		labels.append("static")
	status = worker_class.get_status()
	if status:
		labels.append(status)

	form = render_template("components/create-dataset-option.html", options=worker_options, labels=labels)
	html = render_template_string(form, datasource_id=datasource_id, datasource=datasource)

	return jsonify({
		"status": "success",
		"datasource": datasource_id,
		"type": labels,
		"html": html
	})


@app.route("/api/import-dataset/", methods=["POST"])
@login_required
@limiter.limit("5 per minute")
@openapi.endpoint("tool")
@setting_required("privileges.can_create_dataset")
def import_dataset():
	"""
	Import a dataset from another tool via upload

	Currently only Zeeschuimer is explicitly supported. Receives a file,
	stores it at a temporary location, and runs the search worker for the given
	platform with a "file" parameter pointing to the temporary location. The
	search worker should then parse the data file and finish the dataset.

	The data should be sent in the request body, as a POST request.

    :request-param str ?access_token:  Access token; only required if not
                                       logged in currently.

	:return-error 404:  If the platform specified in the
						`X-Zeeschuimer-Platform` header is not known

	:return-schema: {
		type=object,
		properties={
			status={type=string},
			key={type=string},
			url={type=integer}
		}
	}
	"""
	platform = request.headers.get("X-Zeeschuimer-Platform").split(".")[0]
	if not platform or platform not in backend.all_modules.datasources or platform not in config.get('datasources.enabled'):
		return error(404, message="Unknown platform or source format")

	worker_types = (f"{platform}-import", f"{platform}-search")
	worker = None
	for worker_type in worker_types:
		worker = backend.all_modules.workers.get(worker_type)
		if worker:
			break

	if not worker:
		return error(404, message="Unknown platform or source format")

	dataset = DataSet(
		parameters={"datasource": platform},
		type=worker.type,
		db=db,
		owner=current_user.get_id(),
		extension=worker.extension
	)
	dataset.update_status("Importing uploaded file...")

	# store the file at the result path for the dataset, but with a different suffix
	# since the dataset was only just created, this file is guaranteed to not exist yet
	# cleaning it up later is left as an exercise for the search worker
	temporary_path = dataset.get_results_path().with_suffix(".importing")
	dataset.file = str(temporary_path)

	with temporary_path.open("wb") as outfile:
		while True:
			chunk = request.stream.read(4096)
			if len(chunk) == 0:
				break

			outfile.write(chunk)

	job = queue.add_job(worker_type, {"file": str(temporary_path)}, dataset.key)
	dataset.link_job(job)

	return jsonify({
		"status": "queued",
		"key": dataset.key,
		"url": url_for("show_result", key=dataset.key)
	})


@app.route("/api/queue-query/", methods=["POST"])
@login_required
@setting_required("privileges.can_create_dataset")
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

	# handle confirmation outside of parameter parsing, since it is not data
	# source specific
	has_confirm = bool(request.form.get("frontend-confirm", False))

	if hasattr(search_worker, "validate_query"):
		# queries are always validated, also if they have been validated before,
		# just in case
		try:
			# first sanitise values
			sanitised_query = UserInput.parse_all(search_worker.get_options(None, current_user), request.form, silently_correct=False)

			# then validate for this particular datasource
			sanitised_query = {"frontend-confirm": has_confirm, **sanitised_query}
			sanitised_query = search_worker.validate_query(sanitised_query, request, current_user)

		except QueryNeedsFurtherInputException as e:
			# ask the user for more input by returning a HTML snippet
			# containing form fields to be added to the form before it is
			# re-submitted
			form = render_template("components/create-dataset-option.html", options=e.config)
			return jsonify({"status": "extra-form", "html": form})

		except QueryParametersException as e:
			# parameters need amending
			return jsonify({"status": "error", "message": "Cannot create a dataset with these parameters. %s" % e})

		except QueryNeedsExplicitConfirmationException as e:
			# parameters are OK, but we need to be sure the user wants this
			# (because it will e.g. take a long time)
			return jsonify({"status": "confirm", "message": str(e)})

	else:
		raise NotImplementedError("Data sources MUST sanitise input values with validate_query")

	# parameters OK, front-end can submit for real
	# why not just continue? because the initial validation is done with
	# potentially fragmentary input, e.g. only the first bytes of a file upload
	# are sent for validation. This makes the front-end re-submit the full
	# query
	if not has_confirm:
		return jsonify({"status": "validated", "keep": sanitised_query})

	sanitised_query["datasource"] = datasource_id
	sanitised_query["type"] = search_worker_id

	if request.form.to_dict().get("pseudonymise") in ("pseudonymise", "anonymise"):
		sanitised_query["pseudonymise"] = request.form.to_dict().get("pseudonymise")

	if request.form.to_dict().get("email-complete", False):
		sanitised_query["email-complete"] = request.form.to_dict().get("email-user", False)

	# unchecked checkboxes do not send data in html forms, so key will not exist if box is left unchecked
	is_private = bool(request.form.get("make-private", False))

	extension = search_worker.extension if hasattr(search_worker, "extension") else "csv"

	dataset = DataSet(
		parameters=sanitised_query,
		db=db,
		type=search_worker_id,
		extension=extension,
		is_private=is_private,
		owner=current_user.get_id()
	)

	# this bit allows search workers to insist on the new dataset having a
	# certain key. This is at the time of writing only used by the worker that
	# imports 4CAT datasets from elsewhere
	if hasattr(search_worker, "ensure_key"):
		dataset.set_key(search_worker.ensure_key(sanitised_query))

	if request.form.get("label"):
		dataset.update_label(request.form.get("label"))

	if hasattr(search_worker, "after_create"):
		search_worker.after_create(sanitised_query, dataset, request)

	queue.add_job(jobtype=search_worker_id, remote_id=dataset.key)
	dataset.link_job(Job.get_by_remote_ID(dataset.key, db))

	return jsonify({"status": "success", "message": "", "key": dataset.key})


@app.route('/api/check-query/')
@setting_required("privileges.can_create_dataset")
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
			is_favourite={type=boolean},
			url={type=string}
		}
	}

	:return-error 404:  If the dataset does not exist.
	"""
	dataset_key = request.args.get("key")
	block = request.args.get("block", "status")

	try:
		dataset = DataSet(key=dataset_key, db=db)
	except DataSetException:
		return error(404, error="Dataset does not exist.")

	if not current_user.can_access_dataset(dataset):
		return error(403, error="Dataset is private")

	results = dataset.check_dataset_finished()
	if results == 'empty':
		dataset_data = dataset.data
		dataset_data["parameters"] = json.loads(dataset_data["parameters"])
		path = False
	elif results:
		# Return absolute folder when using localhost for debugging
		path = results.name
		dataset_data = dataset.data
		dataset_data["parameters"] = json.loads(dataset_data["parameters"])
	else:
		path = ""

	template = "components/result-status.html" if block == "status" else "components/result-result-row.html"

	status = {
		"datasource": dataset.parameters.get("datasource"),
		"status": dataset.get_status(),
		"status_html": render_template(template, dataset=dataset),
		"label": dataset.get_label(),
		"rows": dataset.data["num_rows"],
		"key": dataset_key,
		"done": True if dataset.is_finished() else False,
		"path": path,
		"progress": round(dataset.get_progress() * 100),
		"empty": (dataset.data["num_rows"] == 0),
		"is_favourite": (db.fetchone("SELECT COUNT(*) AS num FROM users_favourites WHERE name = %s AND key = %s",
									 (current_user.get_id(), dataset.key))["num"] > 0),
		"url": url_for("show_result", key=dataset.key, _external=True)
	}

	return jsonify(status)

@app.route("/api/edit-dataset-label/<string:key>/", methods=["POST"])
@api_ratelimit
@login_required
@openapi.endpoint("tool")
def edit_dataset_label(key):
	"""
	Change label for a dataset

	Only allowed for dataset owner or admin!

	:request-param str key:  ID of the dataset for which to change the label
	:return: Label info, containing the dataset `key`, the dataset `url`,
	         and the new `label`.

	:return-schema: {
		type=object,
		properties={
			key={type=string},
			url={type=string},
			label={type=string}
		}
	}

	:return-error 404:  If the dataset does not exist.
	:return-error 403:  If the user is not owner of the dataset or an admin
	"""
	dataset_key = request.form.get("key", "") if not key else key
	label = request.form.get("label", "")

	try:
		dataset = DataSet(key=dataset_key, db=db)
	except DataSetException:
		return error(404, error="Dataset does not exist.")

	if not config.get("privileges.admin.can_manipulate_all_datasets") and not dataset.is_accessible_by(current_user, "owner"):
		return error(403, message="Not allowed")

	dataset.update_label(label)
	return jsonify({
		"key": dataset.key,
		"url": url_for("show_result", key=dataset.key),
		"label": dataset.get_label()
	})


@app.route("/api/convert-dataset/<string:key>/", methods=["POST"])
@api_ratelimit
@login_required
@openapi.endpoint("tool")
def convert_dataset(key):
	"""
	Change the type of custom datasets.

	Only allowed for admin!

	:request-param str key: ID of the dataset for which to change the label
	:return: Dataset info, containing the dataset `key`, the dataset `url`,
	         and the new `datasource`.

	:return-schema: {
		type=object,
		properties={
			key={type=string},
			url={type=string},
			datasource={type=string}
		}
	}

	:return-error 404:  If the dataset does not exist.
	:return-error 403:  If the user is not an admin
	"""
	dataset_key = request.form.get("key", "") if not key else key
	datasource = request.form.get("to_datasource", "")

	try:
		dataset = DataSet(key=dataset_key, db=db)
	except DataSetException:
		return error(404, error="Dataset does not exist.")

	if not current_user.is_admin:
		return error(403, message="Not allowed")

	dataset.change_datasource(datasource)
	return jsonify({
		"key": dataset.key,
		"url": url_for("show_result", key=dataset.key),
		"label": dataset.get_label()
	})

@app.route("/api/nuke-query/", methods=["DELETE"])
@api_ratelimit
@login_required
@openapi.endpoint("tool")
def nuke_dataset(key=None, reason=None):
	"""
	Use executive override to cancel a query

	This cancels the running query for a dataset but does not delete the
	dataset; rather it allows the cancelling user to set a reason for the
	cancellation that will be displayed as the 'dataset status' in the
	interface.

	This can *only* be done by admins, *not* by the 'owner' of the dataset
	(unless that user is also an admin).

	:request-param str key:  ID of the dataset to delete
	:request-param str reason:  Deletion reason
	:request-param str ?access_token:  Access token; only required if not
	logged in currently.

	:return: A dictionary with a successful `status`.

	:return-schema: {type=object,properties={status={type=string}}}

	:return-error 404:  If the dataset does not exist.
	:return-error 403:  If the user is not an administrator
	"""
	dataset_key = request.form.get("key", "") if not key else key
	reason = request.form.get("reason", "") if not reason else reason
	if not reason:
		reason = "[no reason given]"

	try:
		dataset = DataSet(key=dataset_key, db=db)
	except DataSetException:
		return error(404, error="Dataset does not exist.")

	if not current_user.is_admin:
		return error(403, message="Not allowed")

	# if there is an active or queued job for some child dataset, cancel and
	# delete it
	children = dataset.get_all_children()
	for child in children:
		try:
			job = Job.get_by_remote_ID(child.key, database=db, jobtype=child.type)
			call_api("cancel-job", {"remote_id": child.key, "jobtype": dataset.type, "level": BasicWorker.INTERRUPT_CANCEL})
			job.finish()
			child.delete()
		except JobNotFoundException:
			pass
		except ConnectionRefusedError:
			return error(500,
						 message="The 4CAT backend is not available. Try again in a minute or contact the instance maintainer if the problem persists.")

	# now cancel and delete the job for this one (if it exists)
	try:
		job = Job.get_by_remote_ID(dataset.key, database=db, jobtype=dataset.type)
		call_api("cancel-job", {"remote_id": dataset.key, "jobtype": dataset.type, "level": BasicWorker.INTERRUPT_CANCEL})
	except JobNotFoundException:
		pass
	except ConnectionRefusedError:
		return error(500,
					 message="The 4CAT backend is not available. Try again in a minute or contact the instance maintainer if the problem persists.")

	# wait for the dataset to actually be cancelled
	time.sleep(2)

	if dataset.get_results_path().exists():
		dataset.get_results_path().unlink()

	dataset.update_status("Dataset cancelled by instance administrator. Reason: %s" % reason)
	dataset.finish(0)

	if request.args.get("redirect") is not None:
		return redirect(url_for("show_result", key=dataset.key))
	else:
		return jsonify({"status": "success", "key": dataset.key})


@app.route("/api/delete-dataset/", defaults={"key": None}, methods=["DELETE", "GET", "POST"])
@app.route("/api/delete-dataset/<string:key>/", methods=["DELETE", "GET", "POST"])
@api_ratelimit
@login_required
@openapi.endpoint("tool")
def delete_dataset(key=None):
	"""
	Delete a dataset

	Only available to administrators and dataset owners. Deletes a dataset, as
	well as any children linked to it, from 4CAT. Also tells the backend to stop
	any jobs dealing with the dataset.

	:request-param str key:  ID of the dataset to delete
    :request-param str ?access_token:  Access token; only required if not
    logged in currently.

	:return: A dictionary with a successful `status`.

	:return-schema: {type=object,properties={status={type=string}}}

	:return-error 404:  If the dataset does not exist.
	"""
	dataset_key = request.form.get("key", "") if not key else key

	try:
		dataset = DataSet(key=dataset_key, db=db)
	except DataSetException:
		return error(404, error="Dataset does not exist.")

	if not config.get("privileges.admin.can_manipulate_all_datasets") and not dataset.is_accessible_by(current_user, "owner"):
		return error(403, message="Not allowed")

	# if there is an active or queued job for some child dataset, cancel and
	# delete it
	children = dataset.get_all_children()
	for child in children:
		try:
			job = Job.get_by_remote_ID(child.key, database=db, jobtype=child.type)
			call_api("cancel-job", {"remote_id": child.key, "jobtype": dataset.type, "level": BasicWorker.INTERRUPT_CANCEL})
			job.finish()
		except JobNotFoundException:
			pass
		except ConnectionRefusedError:
			return error(500, message="The 4CAT backend is not available. Try again in a minute or contact the instance maintainer if the problem persists.")

	# now cancel and delete the job for this one (if it exists)
	try:
		job = Job.get_by_remote_ID(dataset.key, database=db, jobtype=dataset.type)
		call_api("cancel-job", {"remote_id": dataset.key, "jobtype": dataset.type, "level": BasicWorker.INTERRUPT_CANCEL})
	except JobNotFoundException:
		pass
	except ConnectionRefusedError:
		return error(500,
					 message="The 4CAT backend is not available. Try again in a minute or contact the instance maintainer if the problem persists.")

	# do we have a parent?
	parent_dataset = DataSet(key=dataset.key_parent, db=db) if dataset.key_parent else None

	# and delete the dataset and child datasets
	dataset.delete()

	if request.args.get("redirect") is not None:
		if parent_dataset:
			return redirect(url_for("show_result", key=parent_dataset.key))
		else:
			return redirect(url_for("show_results"))
	else:
		return jsonify({"status": "success", "key": dataset.key})


@app.route("/api/erase-credentials/", methods=["DELETE"])
@api_ratelimit
@login_required
@openapi.endpoint("tool")
def erase_credentials(key=None):
	"""
	Erase sensitive parameters from dataset

	Removes all parameters starting with `api_`. This heuristic could be made
	more expansive if more fine-grained control is required.

	:request-param str key:  ID of the dataset to delete
	:request-param str ?access_token:  Access token; only required if not
	logged in currently.

	:return: A dictionary with a successful `status`.

	:return-schema: {type=object,properties={status={type=string}}}

	:return-error 404:  If the dataset does not exist.
	:return-error 403:  If the user is not an administrator or the owner
	"""
	dataset_key = request.form.get("key", "") if not key else key

	try:
		dataset = DataSet(key=dataset_key, db=db)
	except DataSetException:
		return error(404, error="Dataset does not exist.")

	if not config.get("privileges.admin.can_manipulate_all_datasets") and not dataset.is_accessible_by(current_user, "owner"):
		return error(403, message="Not allowed")

	for field in dataset.parameters:
		if field.startswith("api_"):
			dataset.delete_parameter(field, instant=True)

	if request.args.get("redirect") is not None:
		flash("Credentials erased.")
		return redirect(url_for("show_result", key=dataset.key))
	else:
		return jsonify({"status": "success", "key": dataset.key})


@app.route("/api/remove-tag/", methods=["GET"])
@api_ratelimit
@login_required
@setting_required("privileges.admin.can_manage_tags")
@openapi.endpoint("tool")
def remove_tag():
	"""
	Remove tag from all users with that tag

	:return: A dictionary with a successful `status`.

	:return-schema: {type=object,properties={status={type=string}}}

	:return-error 403:  If the user is not an administrator or the owner
	:request-param str tag:  Tag to remove
	"""
	tag = request.args.get("tag")

	tagged_users = db.fetchall("SELECT * FROM users WHERE tags @> %s ", (json.dumps([tag]),))
	all_tags = list(set(itertools.chain(*[u["tags"] for u in db.fetchall("SELECT DISTINCT tags FROM users")])))

	for user in tagged_users:
		user = User.get_by_name(db, user["name"])
		user.remove_tag(tag)

	if tag in all_tags:
		all_tags.remove(tag)

	# all_tags is now our canonical list of tags
	# clean up settings
	# delete all tagged settings for tags that are no longer in use
	configured_tags = [t["tag"] for t in db.fetchall("SELECT DISTINCT tag FROM settings")]
	for configured_tag in configured_tags:
		if configured_tag and configured_tag not in all_tags:
			db.delete("settings", where={"tag": configured_tag})

	config.set("flask.tag_order", all_tags, tag="")

	if request.args.get("redirect") is not None:
		flash("Tag removed.")
		return redirect(url_for("manipulate_tags"))
	else:
		return jsonify({"status": "success"})

@app.route("/api/add-dataset-owner/", methods=["POST"])
@api_ratelimit
@login_required
@openapi.endpoint("tool")
def add_dataset_owner(key=None, username=None, role=None):
	"""
	Add an owner to the dataset

	Add a user (if they exist) as an owner to the given dataset. The role of
	the owner can be specified ('owner' or 'viewer') and will determine what
	they can do with the dataset. If the user is already an owner, the role
	is potentially updated.

	:request-param str key:  ID of the dataset to add an owner to
	:request-param str username:  Username to add as owner
	:request-param str role?:  Role to add. Defaults to 'owner'.

	:return: A dictionary with a successful `status`.

	:return-schema: {type=object,properties={status={type=string},html={type=string},key={type=string}}}

	:return-error 404:  If the dataset or user do not exist.
	:return-error 403:  If the user is not an administrator or the owner

	:param str key:  Dataset key; `None` will use the GET parameter
	:param str username:  Username; `None` will use the GET parameter
	:param str role:  Role; `None` will use the GET parameter
	"""
	dataset_key = request.form.get("key", "") if not key else key
	username = request.form.get("name", "") if not username else username

	try:
		dataset = DataSet(key=dataset_key, db=db)
	except DataSetException:
		return error(404, error="Dataset does not exist.")

	if not config.get("privileges.admin.can_manipulate_all_datasets") and not dataset.is_accessible_by(current_user, "owner"):
		return error(403, message="Not allowed")

	new_owner = User.get_by_name(db, username)
	if new_owner is None and not username.startswith("tag:"):
		return error(404, error=f"The user '{username}' does not exist. Use tag:example to add a tag as an owner.")

	role = request.form.get("role", "owner") if not role else role
	if role not in ("owner", "viewer"):
		role = "owner"

	dataset.add_owner(username, role)
	html = render_template("components/dataset-owner.html", owner=username, role=role,
								  current_user=current_user, dataset=dataset)

	if request.args.get("redirect") is not None:
		flash("Dataset owner added.")
		return redirect(url_for("show_result", key=dataset_key))
	else:
		return jsonify({
			"status": "success",
			"key": dataset.key,
			"html": html
		})


@app.route("/api/remove-dataset-owner/", methods=["DELETE"])
@api_ratelimit
@login_required
@openapi.endpoint("tool")
def remove_dataset_owner(key=None, username=None):
	"""
	Add an owner to the dataset

	Remove a user (if they exist) as an owner from the given dataset. If no
	owners are left afterwards, the dataset will be owned by 'anonymous'.

	:request-param str key:  ID of the dataset to remove an owner from
	:request-param str username:  Username to remove as owner

	:return: A dictionary with a successful `status`.

	:return-schema: {type=object,properties={status={type=string},key={type=string}}}

	:return-error 404:  If the dataset or user do not exist.
	:return-error 403:  If the user is not an administrator or the owner

	:param str key:  Dataset key; `None` will use the GET parameter
	:param str username:  Username; `None` will use the GET parameter
	"""
	dataset_key = request.form.get("key", "") if not key else key
	username = request.form.get("name", "") if not username else username

	try:
		dataset = DataSet(key=dataset_key, db=db)
	except DataSetException:
		return error(404, error="Dataset does not exist.")

	if not config.get("privileges.admin.can_manipulate_all_datasets") and not dataset.is_accessible_by(current_user, "owner"):
		return error(403, error="Not allowed")

	if username == current_user.get_id():
		return error(403, error="You cannot remove yourself from a dataset.")

	owner = User.get_by_name(db, username)
	if owner is None and not username.startswith("tag:"):
		return error(404, error="User does not exist.")

	dataset.remove_owner(username)

	if request.args.get("redirect") is not None:
		flash("Dataset owner removed.")
		return redirect(url_for("show_result", key=dataset_key))
	else:
		return jsonify({"status": "success", "key": dataset.key})


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
	except DataSetException:
		return error(404, error="Dataset does not exist.")

	if not current_user.can_access_dataset(dataset):
		return error(403, error="This dataset is private")

	current_status = db.fetchone("SELECT * FROM users_favourites WHERE name = %s AND key = %s",
								 (current_user.get_id(), dataset.key))
	if not current_status:
		db.insert("users_favourites", data={"name": current_user.get_id(), "key": dataset.key})
	else:
		db.delete("users_favourites", where={"name": current_user.get_id(), "key": dataset.key})

	if request.args.get("redirect") is not None:
		flash("Dataset favourite status updated.")
		return redirect(url_for("show_result", key=dataset.key))
	else:
		return jsonify({"success": True, "favourite_status": not current_status})

@app.route("/api/toggle-dataset-private/<string:key>")
@login_required
@openapi.endpoint("tool")
def toggle_private(key):
	"""
	Toggle whether a dataset is private or not

	Private datasets cannot be viewed by users that are not an admin or the
	owner of the dataset. An exception is datasets assigned to the user
	'anonymous', which can be viewed by anyone. Only admins and owners can
	toggle private status of a dataset.

	:param str key: Key of the dataset to mark as (not) private

	:return: A JSON object with the status of the request
	:return-schema: {type=object,properties={success={type=boolean},is_private={type=boolean}}}

	:return-error 404:  If the dataset key was not found
	"""
	try:
		dataset = DataSet(key=key, db=db)
	except DataSetException:
		return error(404, error="Dataset does not exist.")

	if not config.get("privileges.admin.can_manipulate_all_datasets") and not dataset.is_accessible_by(current_user, "owner"):
		return error(403, error="This dataset is private")

	# apply status to dataset and all children
	dataset.is_private = not dataset.is_private
	dataset.update_children(is_private=dataset.is_private)

	if request.args.get("redirect") is not None:
		flash("Dataset private status toggled.")
		return redirect(url_for("show_result", key=dataset.key))
	else:
		return jsonify({"success": True, "is_private": dataset.is_private})

@app.route("/api/queue-processor/", methods=["POST"])
@api_ratelimit
@login_required
@setting_required("privileges.can_run_processors")
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
			return error(400, error="No file input provided")

		if input_file.filename[-4:] != ".csv":
			return error(400, error="File input is not a csv file")

		test_csv_file = csv.DictReader(input_file.stream)
		if "body" not in test_csv_file.fieldnames:
			return error(400, error="File must contain a 'body' column")

		filename = secure_filename(input_file.filename)
		input_file.save(str(config.get('PATH_DATA')) + "/")

	elif not key:
		key = request.form.get("key", "")

	if not processor:
		processor = request.form.get("processor", "")

	# cover all bases - can only run processor on "parent" dataset
	try:
		dataset = DataSet(key=key, db=db)
	except DataSetException:
		return error(404, error="Not a valid dataset key.")

	if not config.get("privileges.admin.can_manipulate_all_datasets") and not current_user.can_access_dataset(dataset):
		return error(403, error="You cannot run processors on private datasets")

	# check if processor is available for this dataset
	available_processors = dataset.get_available_processors(user=current_user)
	if processor not in available_processors:
		return error(404, error="This processor is not available for this dataset or has already been run.")

	# create a dataset now
	try:
		options = UserInput.parse_all(available_processors[processor].get_options(dataset, current_user), request.form, silently_correct=False)
	except QueryParametersException as e:
		return error(400, error=str(e))

	if request.form.to_dict().get("email-complete", False):
		options["email-complete"] = request.form.to_dict().get("email-user", False)

	# private or not is inherited from parent dataset
	analysis = DataSet(parent=dataset.key,
					   parameters=options,
					   db=db,
					   extension=available_processors[processor].get_extension(parent_dataset=dataset),
					   type=processor,
					   is_private=dataset.is_private,
					   owner=current_user.get_id()
	)

	# give same ownership as parent dataset
	analysis.copy_ownership_from(dataset)

	if analysis.is_new:
		# analysis has not been run or queued before - queue a job to run it
		queue.add_job(jobtype=processor, remote_id=analysis.key)
		job = Job.get_by_remote_ID(analysis.key, database=db)
		analysis.link_job(job)
		analysis.update_status("Queued")
	else:
		flash("This analysis (%s) is currently queued or has already been run with these parameters." %
			  available_processors[processor].title)

	return jsonify({
		"status": "success",
		"container": "*[data-dataset-key=" + dataset.key + "]",
		"key": analysis.key,
		"html": render_template("components/result-child.html", child=analysis, dataset=dataset, parent_key=dataset.key,
                                processors=backend.all_modules.processors) if analysis.is_new else "",
		"messages": get_flashed_messages(),
		"is_filter": available_processors[processor].is_filter()
	})


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
		except DataSetException:
			continue

		if not current_user.can_access_dataset(dataset):
			continue

		genealogy = dataset.get_genealogy()
		parent = genealogy[-2]
		top_parent = genealogy[0]

		children.append({
			"key": dataset.key,
			"finished": dataset.is_finished(),
			"progress": round(dataset.get_progress() * 100),
			"html": render_template("components/result-child.html", child=dataset, dataset=parent,
                                    query=dataset.get_genealogy()[0], parent_key=top_parent.key,
                                    processors=backend.all_modules.processors),
			"resultrow_html": render_template("components/result-result-row.html", dataset=top_parent),
			"url": "/result/" + dataset.data["result_file"]
		})

	return jsonify(children)


@app.route("/api/request-token/")
@login_required
@setting_required("privileges.can_create_api_token")
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

@app.route("/api/export-packed-dataset/<string:key>/<string:component>/")
@login_required
@setting_required("privileges.can_export_datasets")
def export_packed_dataset(key=None, component=None):
	"""
	Export dataset for importing in another 4CAT instance

	:param key:
	:param component:
	:return:
	"""
	try:
		dataset = DataSet(key=key, db=db)
	except DataSetException:
		return error(404, error="Dataset not found.")

	if not current_user.can_access_dataset(dataset=dataset, role="owner"):
		return error(403, error=f"You cannot export this dataset. {current_user}")

	if not dataset.is_finished():
		return error(403, error="You cannot export unfinished datasets.")

	if component == "metadata":
		metadata = db.fetchone("SELECT * FROM datasets WHERE key = %s", (dataset.key,))

		# get 4CAT version (presumably to ensure export is compatible with import)
		metadata["current_4CAT_version"] = get_software_version()
		return jsonify(metadata)

	elif component == "children":
		children = [d["key"] for d in db.fetchall("SELECT key FROM datasets WHERE key_parent = %s AND is_finished = TRUE", (dataset.key,))]
		return jsonify(children)

	elif component in ("data", "log"):
		filepath = dataset.get_results_path() if component == "data" else dataset.get_results_path().with_suffix(".log")
		if not filepath.exists():		# def stream_data_content(datafile):
			return error(404, error=f"File for {component} not found")
		else:
			return send_from_directory(directory=filepath.parent, path=filepath.name)

	else:
		return error(406, error="Dataset component unknown")
