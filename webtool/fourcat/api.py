import sys
import os
import psutil

sys.path.insert(0, os.path.dirname(__file__) + '/../..')
sys.path.insert(0, os.path.dirname(__file__) + '/../../backend')

from flask import jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import config
from fourcat import app
from lib.database import Database
from lib.logger import Logger
from lib.helpers import get_absolute_folder

log = Logger()
limiter = Limiter(app, key_func=get_remote_address)
api_ratelimit = limiter.shared_limit("1 per second", scope="api")

API_SUCCESS = 200
API_FAIL = 404


@app.route('/api/')
@api_ratelimit
def api_main():
	"""
	API Index

	No data here - just a reference to the documentation

	:return: Flask JSON response
	"""
	response = {
		"code": API_SUCCESS,
		"items": [
			"Refer to https://4cat.oilab.nl/api.md for API documentation."
		]
	}

	return jsonify(response)


@app.route('/api/status.json')
@api_ratelimit
def api_status():
	"""
	Get service status

	:return: Flask JSON response
	"""

	# get job stats
	db = Database(logger=log)
	jobs = db.fetchall("SELECT * FROM jobs")
	jobs_count = len(jobs)
	jobs_types = set([job["jobtype"] for job in jobs])
	jobs_sorted = {jobtype: len([job for job in jobs if job["jobtype"] == jobtype]) for jobtype in jobs_types}
	jobs_sorted["total"] = jobs_count
	db.close()

	# determine if backend is live by checking if the process is running

	lockfile = get_absolute_folder(config.PATH_LOCKFILE) + "/4cat-backend.lock"
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
