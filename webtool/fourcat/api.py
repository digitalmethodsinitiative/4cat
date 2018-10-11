import sys
import os
import psutil
sys.path.insert(0, os.path.dirname(__file__) +  '/../../backend')
from lib.database import Database
from lib.logger import Logger
from fourcat import app
from flask import jsonify

log = Logger()
db = Database(logger=log)

API_SUCCESS = 200
API_FAIL = 404

@app.route('/api/')
def api_main():
    response = {
        "code": API_SUCCESS,
        "items": [
            "Refer to https://4cat.oilab.nl/api.md for API documentation."
        ]
    }

    return jsonify(response)

@app.route('/api/status/')
def api_status():
    jobs = db.fetchall("SELECT * FROM jobs")
    jobs_count = len(jobs)
    jobs_types = set([job["jobtype"] for job in jobs])
    jobs_sorted = {jobtype: len([job for job in jobs if job["jobtype"] == jobtype]) for jobtype in jobs_types}

    lockfile = "../../backend/4cat-backend.lock"
    if os.path.isfile("../../backend/4cat-backend.lock"):
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
                "queued": jobs_count,
                "queued_sorted": jobs_sorted
            },
            "frontend": {
                "live": True  # duh
            }
        }
    }

    return jsonify(response)