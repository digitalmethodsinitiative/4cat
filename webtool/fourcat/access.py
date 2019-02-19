"""
Control access to web tool
"""
import html2text
import hashlib
import smtplib
import fnmatch
import socket
import time
import json
import sys
import os

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

sys.path.insert(0, os.path.dirname(__file__) + '/../..')
import config

from flask import request, abort, render_template, redirect, url_for, flash, get_flashed_messages, jsonify
from flask_login import login_user, login_required, logout_user, current_user
from fourcat import app, login_manager, openapi, db
from fourcat.api import limiter
from fourcat.user import User


@login_manager.user_loader
def load_user(user_name):
	"""
	Load user object

	Required for Flask-Login.
	:param user_name:  ID of user
	:return:  User object
	"""
	user = User.get_by_name(user_name)
	user.authenticate()
	return user


@login_manager.request_loader
def load_user_from_request(request):
	"""
	Load user object via access token

	:param request:  Flask request
	:return:  User object, or None if no valid access token was given
	"""
	user = db.fetchone("SELECT name AS user FROM access_tokens WHERE token = %s AND (expires = 0 OR expires > %s)",
					   (request.args.get("access-token"), int(time.time())))
	if not user:
		return None
	else:
		db.execute("UPDATE access_tokens SET calls = calls + 1 WHERE name = %s", (user["user"],))
		user = User.get_by_name(user["user"])
		user.authenticate()
		return user


@app.before_request
def autologin_whitelist():
	"""
	Checks if host name matches whitelisted hostmask. If so, the user is logged
	in as the special "autologin" user.
	"""
	if not config.FlaskConfig.HOSTNAME_WHITELIST:
		# if there's not whitelist, there's no point in checking it
		return

	if "/static/" in request.path:
		# never check login for static files
		return

	try:
		socket.setdefaulttimeout(2)
		hostname = socket.gethostbyaddr(request.remote_addr)[0]
	except (socket.herror, socket.timeout):
		return

	if current_user:
		if current_user.get_id() == "autologin":
			# whitelist should be checked on every request
			logout_user()
		elif current_user.is_authenticated:
			# if we're logged in as a regular user, no need for a check
			return

	# uva is a special user that is automatically logged in for this request only
	# if the hostname matches the whitelist
	for hostmask in config.FlaskConfig.HOSTNAME_WHITELIST:
		if fnmatch.filter([hostname], hostmask):
			autologin_user = User.get_by_name("autologin")
			if not autologin_user:
				# this user should exist by default
				abort(500)
			autologin_user.authenticate()
			login_user(autologin_user, remember=False)


@limiter.request_filter
def exempt_from_limit():
	"""
	Checks if host name matches whitelisted hostmasks for exemption from API
	rate limiting.

	:return bool:  Whether the request's hostname is exempt
	"""
	if not config.FlaskConfig.HOSTNAME_WHITELIST_API:
		return False

	try:
		socket.setdefaulttimeout(2)
		hostname = socket.gethostbyaddr(request.remote_addr)[0]
	except (socket.herror, socket.timeout):
		return False

	for hostmask in config.FlaskConfig.HOSTNAME_WHITELIST_API:
		if fnmatch.filter([hostname], hostmask):
			return True

	return False


@app.route('/login', methods=['GET', 'POST'])
def show_login():
	"""
	Handle logging in

	If not submitting a form, show form; if submitting, check if login is valid
	or not.

	:return: Redirect to either the URL form, or the index (if logged in)
	"""
	if current_user.is_authenticated:
		return redirect(url_for("show_index"))

	if request.method == 'GET':
		return render_template('login.html', flashes=get_flashed_messages())

	username = request.form['username']
	password = request.form['password']
	registered_user = User.get_by_login(username, password)

	if registered_user is None:
		flash('Username or Password is invalid', 'error')
		return redirect(url_for('show_login'))

	login_user(registered_user, remember=True)

	return redirect(url_for("show_index"))


@app.route("/logout")
@login_required
def logout():
	"""
	Log a user out

	:return:  Redirect to URL form
	"""
	logout_user()
	flash("You have been logged out of 4CAT.")
	return redirect(url_for("show_login"))


@app.route("/request-token/")
@login_required
@openapi.endpoint
def request_token():
	"""
	Request an access token

	Requires that the user is currently logged in to 4CAT.

	:return: An object with one item `token`
	"""
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

	return jsonify(token)

@app.route("/request-access/", methods=["GET", "POST"])
def request_access():
	if not config.ADMIN_EMAILS:
		return render_template("error.html", message="No administrator e-mail is configured; the request form cannot be displayed.")

	if not config.MAILHOST:
		return render_template("error.html", message="No e-mail server configured; the request form cannot be displayed.")

	incomplete = []

	if request.method == "POST":
		required = ("name", "email", "university", "intent", "source")
		for field in required:
			if not request.form.get(field, "").strip():
				incomplete.append(field)

		if incomplete:
			flash("Please fill in all fields before submitting.")
		else:
			html_parser = html2text.HTML2Text()

			sender = "4cat@oilab.nl"
			message = MIMEMultipart("alternative")
			message["Subject"] = "Account request"
			message["From"] = sender
			message["To"] = config.ADMIN_EMAILS[0]

			mail = "<p>Hello! Some requests a 4CAT Account:</p>\n"
			for field in required:
				mail += "<p><b>" + field + "</b>: " + request.form.get(field, "") + " </p>\n"

			message.attach(MIMEText(html_parser.handle(mail), "plain"))
			message.attach(MIMEText(mail, "html"))

			try:
				with smtplib.SMTP("localhost") as smtp:
					smtp.sendmail("4cat@oilab.nl", config.ADMIN_EMAILS, message.as_string())
				return render_template("error.html", title="Thank you", message="Your request has been submitted; we'll try to answer it as soon as possible.")
			except (smtplib.SMTPException, ConnectionRefusedError):
				return render_template("error.html", title="Error", message="The form could not be submitted; the e-mail server is unreachable.")

	return render_template("request-account.html", incomplete=incomplete, flashes=get_flashed_messages(), form=request.form)