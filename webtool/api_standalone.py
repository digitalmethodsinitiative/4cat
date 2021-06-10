"""
Standalone API - allows running data through processors without having to first
create a 4CAT data set, et cetera. Primarily intended to allow easier use of
4CAT within the PENELOPE framework.
"""

import json
import time
import csv

import backend

from flask import jsonify, request, send_file, after_this_request
from flask_login import login_required, current_user

from webtool import app, db, log, openapi, limiter
from webtool.lib.helpers import error

from common.lib.exceptions import JobNotFoundException
from common.lib.queue import JobQueue
from common.lib.job import Job
from common.lib.dataset import DataSet

api_ratelimit = limiter.shared_limit("45 per minute", scope="api")

API_SUCCESS = 200
API_FAIL = 404

csv.field_size_limit(1024 * 1024 * 1024)

@app.route("/api/get-standalone-processors/")
@api_ratelimit
@openapi.endpoint("standalone")
def get_standalone_processors():
	"""
	Get processors available for standalone API requests

	:return: A JSON object, a list with processor IDs that may be used for the
	`/api/process/<processor>/` endpoint as keys and a `description` of what
	the processor does, a `name` and the processor's `category`.

	:return-schema: {
		type=object,
		additionalProperties={
			type=object,
			properties={
				description={type=string},
				name={type=string},
				category={type=string}
			}
		}
	}
	"""
	available_processors = {}

	for processor in backend.all_modules.processors:
		if not backend.all_modules.processors[processor].hasattr("datasources") and not hasattr(backend.all_modules.processors[processor], "accepts"):
			available_processors[processor] = backend.all_modules.processors[processor]

	return jsonify({processor: {
		"name": available_processors[processor].name,
		"category": available_processors[processor].category,
		"description": available_processors[processor].description,
		"extension": available_processors[processor].extension
	} for processor in available_processors})

@app.route("/api/process/<processor>/", methods=["POST"])
@api_ratelimit
@login_required
@openapi.endpoint("standalone")
def process_standalone(processor):
	"""
	Run a standalone processor

	This bypasses the usual 4CAT query-processor structure and allows running
	any available processor (see the `/api/get-standalone-processors/`
	endpoint) with one API call. The data is returned immediately and not saved
	server-side.

	Requires authentication.

	:param str processor:  ID of the processor to run on incoming data

	:request-body object data:  Data to process, a JSON-formatted list of
	objects with each object having at least they keys `post_id`,
	`thread_id`, body`, and `author`.

	:request-schema data: {
		type=object,
		properties={
			post_id={type=string},
			thread_id={type=string},
			body={type=string},
			author={type=string}
		}
	}

    :request-param str ?access_token:  Access token; only required if not
                                       logged in currently.

	:return:  A JSON object containing the processed data, with a
	processor-specific structure.

	:return-schema: {
		type=object,
		additionalProperties={}
	}

	:return-error 402: If an invalid processor is requested, or if the input is
	not properly-formatted JSON.
	:return-error 503: If too many other requests are currently being handled,
	so that the server does not have the capacity to deal with this request
	"""
	processors = get_standalone_processors().get_json()

	if processor not in processors:
		return error(402, error="Processor '%s' is not available" % processor)

	if not request.is_json:
		return error(402, error="This API endpoint only accepts JSON-formatted data as input")

	try:
		input = request.get_json(force=True)
	except json.JSONDecodeError:
		return error(402, error="JSON decoding error")

	# check file integrity
	required = ("id", "thread_id", "body", "author")
	try:
		for row in input:
			for field in required:
				if field not in row:
					return error(402, error="Input is valid JSON, but not a list of data objects (missing field '%s')" % field)
	except TypeError:
		return error(402, error="Input is valid JSON, but not a list of data objects")

	if not input:
		return error(402, error="Input is empty")

	# ok, valid input!
	temp_dataset = DataSet(extension="csv", type="standalone", parameters={"user": current_user.get_id(), "after": [processor]}, db=db)
	temp_dataset.finish(len(input))

	# make sure the file is deleted later, whichever way this request is
	# ultimately handled
	@after_this_request
	def delete_temporary_dataset(response):
		temp_dataset.delete() # also deletes children!
		return response

	# write the input as a csv file so it can be accessed as normal by
	# processors
	result_file = temp_dataset.get_results_path()
	with result_file.open("w") as temp_csv:
		writer = csv.DictWriter(temp_csv, fieldnames=required)
		writer.writeheader()
		for row in input:
			writer.writerow({field: row[field] for field in required})

	# queue the postprocessor
	metadata = processors[processor]
	processed = DataSet(extension=metadata["extension"], type=processor, parent=temp_dataset.key, db=db)

	queue = JobQueue(database=db, logger=log)
	job = queue.add_job(processor, {}, processed.key)
	place_in_queue = queue.get_place_in_queue(job)
	if place_in_queue > 5:
		job.finish()
		return error(code=503, error="Your request could not be handled as there are currently %i other jobs of this type in the queue. Please try again later." % place_in_queue)

	# wait up to half a minute for the job to be taken up
	# if not, tell the user to try again later

	start = time.time()
	while True:
		if time.time() > start + 30:
			job.finish()
			return error(code=503, error="The server is currently too busy to handle your request. Please try again later.")

		if queue.get_place_in_queue(job) != 0:
			time.sleep(2)
			continue
		else:
			break

	# job currently being processed, wait for it to finish
	while True:
		try:
			job = Job.get_by_remote_ID(job.data["remote_id"], db, processor)
		except JobNotFoundException:
			break

		if not job.is_finished:
			time.sleep(2)
		else:
			break

	# job finished, send file - temporary datasets will be cleaned up by
	# after_this_request function defined earlier
	return send_file(processed.get_results_path(), as_attachment=True)