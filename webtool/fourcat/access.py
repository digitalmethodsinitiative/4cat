"""
Control access to web tool
"""
import fnmatch
import socket
import time
import sys
import os

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
	user = db.fetchone("SELECT name AS user FROM tokens WHERE token = ? AND (expires = 0 OR expires > ?)",
					   (request.args.get("access-token"), int(time.time())))
	if not user:
		return None
	else:
		db.execute("UPDATE tokens SET calls = calls + 1 WHERE name = ?", (user["user"],))
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
	token = db.fetchone("SELECT * FROM tokens WHERE name = ? AND (expires = 0 OR expires > ?)",
						(current_user.get_id(), int(time.time())))

	if token:
		token = token["token"]
	else:
		token = "hello"

		# delete any expired tokens
		db.delete("tokens", where={"name": current_user.get_id()})

		# save new token
		db.insert("tokens", data={
			"name": current_user.get_id(),
			"token": token
		})

	return jsonify({"token": token})
