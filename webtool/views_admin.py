"""
4CAT Web Tool views - pages to be viewed by the user
"""
import os
import re
import csv
import json
import glob
import config
import time
import markdown

from pathlib import Path

import backend

from flask import render_template, jsonify, abort, request, redirect, send_from_directory, flash, get_flashed_messages, \
	url_for
from flask_login import login_required, current_user

from webtool import app, db, log
from webtool.lib.helpers import admin_required

from webtool.api_tool import delete_dataset, toggle_favourite, queue_processor

from backend.lib.helpers import call_api

@app.route("/admin/")
@login_required
@admin_required
def admin_frontpage():
	return render_template("controlpanel/frontpage.html")

@app.route("/admin/add-user/")
@login_required
@admin_required
def add_user():
	pass

@app.route("/admin/worker-status/")
@login_required
@admin_required
def get_worker_status():
	workers = call_api("worker-status")["response"]
	return render_template("controlpanel/worker-status.html", workers=workers, worker_types=backend.all_modules.workers, now=time.time())


	pass

@app.route("/admin/queue-status/")
@login_required
@admin_required
def get_queue_status():
	workers = call_api("worker-status")["response"]
	queue = {}
	for worker in workers:
		if not worker["is_running"]:
			if worker["type"] not in queue:
				queue[worker["type"]]  = 0

			queue[worker["type"]] += 1

	return render_template("controlpanel/queue-status.html", queue=queue, worker_types=backend.all_modules.workers, now=time.time())