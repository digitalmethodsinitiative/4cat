"""
4CAT Web Tool views - pages to be viewed by the user
"""
import re
import time
import psycopg2

import backend

from flask import render_template, jsonify, request
from flask_login import login_required, current_user

from webtool import app, db
from webtool.lib.helpers import admin_required, error
from webtool.lib.user import User

from backend.lib.helpers import call_api


@app.route("/admin/")
@login_required
@admin_required
def admin_frontpage():
	return render_template("controlpanel/frontpage.html")


@app.route("/admin/worker-status/")
@login_required
@admin_required
def get_worker_status():
	workers = call_api("worker-status")["response"]
	return render_template("controlpanel/worker-status.html", workers=workers, worker_types=backend.all_modules.workers,
						   now=time.time())

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
				queue[worker["type"]] = 0

			queue[worker["type"]] += 1

	return render_template("controlpanel/queue-status.html", queue=queue, worker_types=backend.all_modules.workers,
						   now=time.time())


@app.route("/admin/add-user/")
@login_required
def add_user():
	"""
	Create a new user

	Sends the user an e-mail with a link through which they can set their
	password.

	:return: Either an html page with a message, or a JSON response, depending
	on whether ?format == html
	"""
	if not current_user.is_authenticated or not current_user.is_admin():
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
