"""
4CAT Web Tool views - pages to be viewed by the user
"""
import re
import time
import smtplib
import psycopg2
import markdown

import backend
import config

from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

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
	workers = call_api("worker-status")["response"]["running"]
	return render_template("controlpanel/worker-status.html", workers=workers, worker_types=backend.all_modules.workers,
						   now=time.time())


@app.route("/admin/queue-status/")
@login_required
@admin_required
def get_queue_status():
	queue = call_api("worker-status")["response"]["queued"]
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
	fmt = request.form.get("format", request.args.get("format", "")).strip()
	force = request.form.get("force", request.args.get("force", None))

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
			if not force:
				response = {**response, **{"message": 'Error: User %s already exists. If you want to re-create the user and re-send the registration e-mail, use [this link](/admin/add-user?email=%s&force=1&format=%s).' % (username, username, fmt)}}
			else:
				# if a user does not use their token in time, maybe you want to
				# be a benevolent admin and give them another change, without
				# having them go through the whole signup again
				user = User.get_by_name(username)
				db.update("users", data={"timestamp_token": int(time.time())}, where={"name": username})

				try:
					user.email_token(new=True)
					response["success"] = True
					response = {**response, **{
						"message": "A new registration e-mail has been sent to %s." % username}}
				except RuntimeError as e:
					response = {**response, **{
						"message": "Token was reset registration e-mail could not be sent to them (%s)." % e}}

	if fmt == "html":
		return render_template("error.html", message=response["message"],
							   title=("New account created" if response["success"] else "Error"))
	else:
		return jsonify(response)


@app.route("/admin/reject-user/", methods=["GET", "POST"])
@login_required
def reject_user():
	"""
	(Politely) reject an account request

	Sometimes, account requests need to be rejected. If you want to let the
	requester know of the rejection, this is the route to use :-)

	:return: HTML form, or message containing the e-mail send status
	"""
	if not current_user.is_authenticated or not current_user.is_admin():
		return error(403, message="This page is off-limits to you.")

	email_address = request.form.get("email", request.args.get("email", "")).strip()
	name = request.form.get("name", request.args.get("name", "")).strip()
	form_message = request.form.get("message", request.args.get("message", "")).strip()

	incomplete = []
	if not email_address:
		incomplete.append("email")

	if not name:
		incomplete.append(name)

	if not form_message:
		incomplete.append(form_message)

	if incomplete:
		if not form_message:
			form_answer = Path(config.PATH_ROOT, "webtool/pages/reject-template.md")
			if not form_answer.exists():
				form_message = "No %s 4 u" % config.TOOL_NAME
			else:
				form_message = form_answer.read_text(encoding="utf-8")
				form_message = form_message.replace("{{ name }}", name)
				form_message = form_message.replace("{{ email }}", email_address)

		return render_template("account/reject.html", email=email_address, name=name, message=form_message, incomplete=incomplete)

	email = MIMEMultipart("alternative")
	email["From"] = config.NOREPLY_EMAIL
	email["To"] = email_address
	email["Subject"] = "Your %s account request" % config.TOOL_NAME

	try:
		html_message = markdown.markdown(form_message)

		email.attach(MIMEText(form_message, "plain"))
		email.attach(MIMEText(html_message, "html"))

		with smtplib.SMTP(config.MAILHOST) as smtp:
			smtp.sendmail(config.NOREPLY_EMAIL, [email_address], email.as_string())
	except (smtplib.SMTPException, ConnectionRefusedError) as e:
		return render_template("error.html", message="Could not send e-mail to %s: %s" % (email_address, e),
						title="Error sending rejection")

	return render_template("error.html", message="Rejection sent to %s." % email_address, title="Rejection sent")