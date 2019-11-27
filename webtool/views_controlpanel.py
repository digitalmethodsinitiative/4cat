import psycopg2
import time
import re

from flask import render_template, jsonify, abort, request, redirect, send_from_directory, flash, get_flashed_messages
from webtool import app, db, queue, openapi
from flask_login import login_required, current_user

from webtool.lib.helpers import error
from webtool.lib.user import User

from backend import all_modules
from backend.lib.helpers import call_api


@app.route("/control-panel/")
@login_required
def cp_index():
	if not current_user.is_admin():
		return error(403, message="This page is off-limits to you.")

	return render_template("controlpanel/index.html")


@app.route("/control-panel/status/")
@login_required
def live_stats():
	if not current_user.is_admin():
		return error(403, message="This page is off-limits to you.")

	worker_stats = call_api("workers")["response"]
	datasources = all_modules.datasources

	for id in datasources:
		del datasources[id]["path"]

	workers = {}
	for worker in worker_stats:
		if worker not in all_modules.workers or worker_stats[worker] == 0:
			continue
		workers[worker] = {
			"id": worker,
			"name": all_modules.workers[worker]["name"],
			"active": worker_stats[worker]
		}

	return jsonify({"workers": workers, "datasources": datasources})


@app.route("/control-panel/add-user/")
@login_required
def add_user():
	if not current_user.is_admin():
		return error(403, message="This page is off-limits to you.")

	response = {"success": False}

	email = request.form.get("email", request.args.get("email", "")).strip()

	if not email or not re.match(r"[^@]+\@.*?\.[a-zA-Z]+", email):
		response = {**response, **{"message": "Please provide a valid e-mail address."}}
	else:
		username = email
		try:
			db.insert("users", data={"name": username, "timestamp_token": int(time.time())})

			user = User.get_by_name(username)
			if user is None:
				response = {**response, **{"message": "User was created but could not be instantiated properly."}}
			else:
				try:
					user.email_token(new=True)
					response["success"] = True
					response = {**response, **{
						"message": "An e-mail containing a link through which the registration can be completed has been sent to %s." % username}}
				except RuntimeError as e:
					response = {**response, **{
						"message": "User was created but the registration e-mail could not be sent to them (%s)." % e}}
		except psycopg2.IntegrityError:
			db.rollback()
			response = {**response, **{"message": "Error: User %s already exists." % username}}

	if request.args.get("format", None) == "html":
		return render_template("error.html", message=response["message"],
							   title=("New account created" if response["success"] else "Error"))
	else:
		return jsonify(response)
