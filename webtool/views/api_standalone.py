"""
Standalone API - allows running data through processors without having to first
create a 4CAT data set, et cetera. Primarily intended to allow easier use of
4CAT within the PENELOPE framework.
"""

import json
import time
import csv

from flask import Blueprint, current_app, jsonify, request, send_file, after_this_request, g
from flask_login import login_required, current_user

from webtool.lib.helpers import error, setting_required

from common.lib.exceptions import JobNotFoundException
from common.lib.job import Job
from common.lib.dataset import DataSet
from backend.lib.search import Search

API_SUCCESS = 200
API_FAIL = 404

csv.field_size_limit(1024 * 1024 * 1024)

component = Blueprint("standalone", __name__)
api_ratelimit = current_app.limiter.shared_limit("45 per minute", scope="api")

@component.route("/api/get-standalone-processors/")
@api_ratelimit
@current_app.openapi.endpoint("standalone")
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
	class FakeDataset():
		"""
		Fake dataset class to allow processor introspection without having
		to create a real dataset.

		This is meant to represent a dataset compatible with /api/process/<processor>/
		
		TODO: this could be modified for a base dataset class for more advanced tests
		"""
		type = "fake_dataset"
		parameters = {"datasource": "fake"} # TODO: refactor how processors check module.parameters.get("datasource") to function call we can override here
		
		def get_extension(self):
			"""
			Return CSV which is expected by /api/process/<processor>/

			NDJSON processors work on CSV and NDJSON
			"""
			return "csv"
		
		def get_media_type(self):
			"""
			Return media type expected by /api/process/<processor>/
			"""
			return "text"
		
		def get_columns(self):
			"""
			Return columns expected by /api/process/<processor>/
			"""
			return ["id", "thread_id", "body", "author"]
		
		def is_top_dataset(self):
			"""
			Return True to indicate that this is a top-level dataset
			"""
			return True
		
		def is_accessible_by(self, user, role="owner"):
			"""
			Return True to indicate that this dataset is accessible by the
			current user
			"""
			# Could check to see if the processors are avaiable to the user,
			# but this is not necessary for the fake dataset
			return True
		
		def is_from_collector(self):
			"""
			Return True to indicate that it is a "datasource"

			This is a lie, but so is the cake
			"""
			return True
			
		def is_dataset(self):
			"""
			Return True to indicate that this is a dataset
			"""
			# TODO: I think all is_compatible_with methods ONLY receive DataSet objects; verify and perhaps modify the functions to specify
			return True
		
		def has_annotations(self):
			"""
			Return False to indicate that this dataset does not have
			annotations
			"""
			return False
		
		def is_rankable(self, multiple_items=False):
			"""
			Return True...

			TODO: Unsure if this makes sense here, but trying no to be exclusive here
			"""
			return True
		
	fake_dataset = FakeDataset()

	available_processors = {}

	for processor_type, processor in g.modules.processors.items():
		# Skip datasources as they do not conform to /api/process/<processor>/ API
		if issubclass(processor, Search) or processor_type.endswith("-search"):
			# ALMOST all datasources are subclasses of Search, almost.
			continue

		# Check if the processor is compatible with the fake dataset
		if hasattr(processor, "is_compatible_with") and not processor.is_compatible_with(fake_dataset):
			continue

		available_processors[processor_type] = processor

	return jsonify({processor: {
		"type": available_processors[processor].type,
		"category": available_processors[processor].category,
		"description": available_processors[processor].description,
		"extension": available_processors[processor].extension
	} for processor in available_processors})

@component.route("/api/process/<processor>/", methods=["POST"])
@api_ratelimit
@login_required
@setting_required("privileges.can_run_processors")
@current_app.openapi.endpoint("standalone")
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
	temp_dataset = DataSet(
		extension="csv",
		type="standalone",
		parameters={"next": [processor]},
		db=g.db,
		owner=current_user.get_id(),
		is_private=True,
		modules=g.modules
	)
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
	processed = DataSet(extension=metadata["extension"], type=processor, parent=temp_dataset.key, db=g.db, modules=g.modules)

	job = g.queue.add_job(jobtype=g.modules[processor], details={}, remote_id=processed)
	place_in_queue = job.get_place_in_queue()
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

		if job.get_place_in_queue() != 0:
			time.sleep(2)
			continue
		else:
			break

	# job currently being processed, wait for it to finish
	while True:
		try:
			job = Job.get_by_remote_ID(job.data["remote_id"], g.db, processor)
		except JobNotFoundException:
			break

		if not job.is_finished:
			time.sleep(2)
		else:
			break

	# job finished, send file - temporary datasets will be cleaned up by
	# after_this_request function defined earlier
	return send_file(processed.get_results_path(), as_attachment=True)