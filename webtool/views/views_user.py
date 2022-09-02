"""
Control access to web tool - views and functions used in handling user access
"""
import html2text
import requests
import smtplib
import fnmatch
import socket
import time
import sys
import os

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

sys.path.insert(0, os.path.dirname(__file__) + '/../..')
import common.config_manager as config
from flask import request, abort, render_template, redirect, url_for, flash, get_flashed_messages, jsonify
from flask_login import login_user, login_required, logout_user, current_user
from webtool import app, login_manager, db
from webtool.views.api_tool import limiter
from webtool.lib.user import User
from webtool.lib.helpers import error
from common.lib.helpers import send_email

from pathlib import Path


@login_manager.user_loader
def load_user(user_name):
    """
    Load user object

    Required for Flask-Login.
    :param user_name:  ID of user
    :return:  User object
    """
    user = User.get_by_name(db, user_name)
    if user:
        user.authenticate()
    return user


@login_manager.request_loader
def load_user_from_request(request):
    """
    Load user object via access token

    Access token may be supplied via a GET parameter or the Authorization
    HTTP header.

    :param request:  Flask request
    :return:  User object, or None if no valid access token was given
    """
    token = request.args.get("access-token")

    if not token:
        token = request.headers.get("Authorization")

    if not token:
        return None

    user = db.fetchone("SELECT name AS user FROM access_tokens WHERE token = %s AND (expires = 0 OR expires > %s)",
                       (token, int(time.time())))
    if not user:
        return None
    else:
        db.execute("UPDATE access_tokens SET calls = calls + 1 WHERE name = %s", (user["user"],))
        user = User.get_by_name(db, user["user"])
        user.authenticate()
        return user


@app.before_request
def banned_users():
    """
    Displays a 'sorry, no 4cat for you' message to banned or deactivated users.
    """
    if current_user and current_user.is_authenticated and current_user.is_deactivated:
        message = "Your 4CAT account has been deactivated and you can no longer access this page."
        if current_user.get_attribute("deactivated.reason"):
            message += "\n\nThe following reason was recorded for your account's deactivation: *"
            message += current_user.get_attribute("deactivated.reason") + "*"

        return render_template("error.html", title="Your account has been deactivated", message=message), 403


@app.before_request
def autologin_whitelist():
    """
    Checks if host name matches whitelisted hostmask or IP. If so, the user is
    logged in as the special "autologin" user.
    """
    if not config.get("flask.autologin.hostnames"):
        # if there's no whitelist, there's no point in checking it
        return

    if "/static/" in request.path:
        # never check login for static files
        return

    # filter by IP address and hostname, if the latter is available
    filterables = [request.remote_addr]
    try:
        socket.setdefaulttimeout(2)
        hostname = socket.gethostbyaddr(request.remote_addr)[0]
        filterables.append(hostname)
    except (socket.herror, socket.timeout):
        pass  # no hostname for this address

    if current_user:
        if current_user.get_id() == "autologin":
            # whitelist should be checked on every request
            logout_user()
        elif current_user.is_authenticated:
            # if we're logged in as a regular user, no need for a check
            return

    # autologin is a special user that is automatically logged in for this
    # request only if the hostname or IP matches the whitelist
    if any([fnmatch.filter(filterables, hostmask) for hostmask in config.get("flask.autologin.hostnames", [])]):
        autologin_user = User.get_by_name(db, "autologin")
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
    if not config.get("flask.autologin.api"):
        return False

    # filter by IP address and hostname, if the latter is available
    filterables = [request.remote_addr]
    try:
        socket.setdefaulttimeout(2)
        hostname = socket.gethostbyaddr(request.remote_addr)[0]
        filterables.append(hostname)
    except (socket.herror, socket.timeout):
        pass  # no hostname for this address

    if any([fnmatch.filter(filterables, hostmask) for hostmask in config.get("flask.autologin.api", [])]):
        return True

    return False


@app.route("/first-run/", methods=["GET", "POST"])
def create_first_user():
    """
    Special route for creating an initial admin user

    This route is only available if there are no admin users in the database
    yet. The user created through this route is always made an admin.

    :return:
    """
    has_admin_user = db.fetchone("SELECT COUNT(*) AS amount FROM users WHERE is_admin = True")
    missing = []
    if has_admin_user["amount"]:
        return error(403, message="The 'first run' page is not available")

    if request.method == 'GET':
        return render_template("account/first-run.html", incomplete=missing, form=request.form)

    username = request.form.get("username").strip()
    password = request.form.get("password").strip()

    if not username:
        missing.append("username")
    else:
        user_exists = db.fetchone("SELECT name FROM users WHERE name = %s", (username,))
        if user_exists:
            flash("The username '%s' already exists and is reserved." % username)
            missing.append("username")

    if not password:
        missing.append("password")

    if missing:
        flash("Please make sure all fields are complete")
        return render_template("account/first-run.html", form=request.form, incomplete=missing,
                               flashes=get_flashed_messages())

    if request.form.get("phone-home"):
        with Path(config.get("path.root"), "config/.current-version").open() as outfile:
            version = outfile.read(64).split("\n")[0].strip()

        payload = {"version": version}
        requests.post(config.get("phone_home_url"), payload)

    db.insert("users", data={"name": username})
    db.commit()
    user = User.get_by_name(db=db, name=username)
    user.set_password(password)

    db.update("users", where={"name": username}, data={"is_admin": True, "is_deactivated": False})
    db.commit()

    flash("The admin user '%s' was created, you can now use it to log in." % username)
    return redirect(url_for("show_login"))


@app.route('/login/', methods=['GET', 'POST'])
def show_login():
    """
    Handle logging in

    If not submitting a form, show form; if submitting, check if login is valid
    or not.

    :return: Redirect to either the URL form, or the index (if logged in)
    """
    if current_user.is_authenticated:
        return redirect(url_for("show_index"))

    has_admin_user = db.fetchone("SELECT * FROM users WHERE is_admin = True")
    if not has_admin_user:
        return redirect(url_for("create_first_user"))

    if request.method == 'GET':
        return render_template('account/login.html', flashes=get_flashed_messages())

    username = request.form['username']
    password = request.form['password']
    registered_user = User.get_by_login(db, username, password)

    if registered_user is None:
        flash('Username or Password is invalid.', 'error')
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


@app.route("/request-access/", methods=["GET", "POST"])
def request_access():
    """
    Request a 4CAT Account

    Displays a web form for people to fill in their details which can then be
    sent to the 4CAT admin via e-mail so they can create an account (if
    approved)
    """
    if not config.get('mail.admin_email'):
        return render_template("error.html",
                               message="No administrator e-mail is configured; the request form cannot be displayed.")

    if not config.get('mail.server'):
        return render_template("error.html",
                               message="No e-mail server configured; the request form cannot be displayed.")

    if current_user.is_authenticated:
        return render_template("error.html", message="You are already logged in and cannot request another account.")

    incomplete = []

    policy_template = Path(config.get('PATH_ROOT'), "webtool/pages/access-policy.md")
    access_policy = ""
    if policy_template.exists():
        access_policy = policy_template.read_text(encoding="utf-8")

    if request.method == "POST":
        required = ("name", "email", "university", "intent", "source")
        for field in required:
            if not request.form.get(field, "").strip():
                incomplete.append(field)

        if incomplete:
            flash("Please fill in all fields before submitting.")
        else:
            html_parser = html2text.HTML2Text()

            sender = config.get('mail.noreply')
            message = MIMEMultipart("alternative")
            message["Subject"] = "Account request"
            message["From"] = sender
            message["To"] = config.get('mail.admin_email', "")

            mail = "<p>Hello! Someone requests a 4CAT Account:</p>\n"
            for field in required:
                mail += "<p><b>" + field + "</b>: " + request.form.get(field, "") + " </p>\n"

            root_url = "https" if config.get("flask.https") else "http"
            root_url += "://%s/admin/" % config.get("flask.server_name")
            approve_url = root_url + "add-user/?format=html&email=%s" % request.form.get("email", "")
            reject_url = root_url + "reject-user/?name=%s&email=%s" % (
            request.form.get("name", ""), request.form.get("email", ""))
            mail += "<p>Use <a href=\"%s\">this link</a> to approve this request and send a password reset e-mail.</p>" % approve_url
            mail += "<p>Use <a href=\"%s\">this link</a> to send a message to this person about why their request was " \
                    "rejected.</p>" % reject_url

            message.attach(MIMEText(html_parser.handle(mail), "plain"))
            message.attach(MIMEText(mail, "html"))

            try:
                send_email(config.get('mail.admin_email'), message)
                return render_template("error.html", title="Thank you",
                                       message="Your request has been submitted; we'll try to answer it as soon as possible.")
            except (smtplib.SMTPException, ConnectionRefusedError, socket.timeout) as e:
                return render_template("error.html", title="Error",
                                       message="The form could not be submitted; the e-mail server is unreachable.")

    return render_template("account/request.html", incomplete=incomplete, flashes=get_flashed_messages(),
                           form=request.form, access_policy=access_policy)


@app.route("/reset-password/", methods=["GET", "POST"])
def reset_password():
    """
    Reset a password

    This page requires a valid reset token to be supplied as a GET parameter.
    If that is satisfied then the user may choose a new password which they can
    then use to log in.
    """
    if current_user.is_authenticated:
        # this makes no sense if you're already logged in
        return render_template("error.html", message="You are already logged in and cannot request another account.")

    token = request.args.get("token", None) or request.form.get("token", None)
    if token is None:
        # we need *a* token
        return render_template("error.html", message="You need a valid reset token to set a password.")

    resetting_user = User.get_by_token(db, token)
    if not resetting_user or resetting_user.is_special:
        # this doesn't mean the token is unknown, but it could be older than 3 days
        return render_template("error.html",
                               message="You need a valid reset token to set a password. Your token may have expired: in this case, you have to request a new one.")

    # check form
    incomplete = []
    if request.method == "POST":
        # check password validity
        password = request.form.get("password", None)
        if password is None or len(password) < 8:
            incomplete.append("password")
            flash("Please provide a password of at least 8 characters.")

        # reset password if okay and redirect to login
        if not incomplete:
            resetting_user.set_password(password)
            resetting_user.clear_token()
            flash("Your password has been set. You can now log in to 4CAT.")
            return redirect(url_for("show_login"))

    # show form
    return render_template("account/reset-password.html", username=resetting_user.get_name(), incomplete=incomplete,
                           flashes=get_flashed_messages(), token=token,
                           form=request.form)


@app.route("/request-password/", methods=["GET", "POST"])
@limiter.limit("6 per minute")
def request_password():
    """
    Request a password reset

    A user that is not logged in can use this page to request that a password
    reset link will be sent to them. Only one link can be requested per 3 days.

    This view is rate-limited to prevent brute forcing a list of e-mails.
    :return:
    """
    if current_user.is_authenticated:
        # using this while logged in makes no sense
        return render_template("error.html", message="You are already logged in and cannot request a password reset.")

    # check form submission
    incomplete = []
    if request.method == "POST":
        # we need *a* username
        username = request.form.get("username", None)
        if username is None:
            incomplete.append(username)
            flash("Please provide a username.")

        # is it also a valid username? that is not a 'special' user (like autologin)?
        resetting_user = User.get_by_name(db, username)
        if resetting_user is None or resetting_user.is_special:
            incomplete.append("username")
            flash("That user is not known here. Note that your username is typically your e-mail address.")

        elif resetting_user.get_token() and resetting_user.data["timestamp_token"] > 0 and resetting_user.data[
            "timestamp_token"] > time.time() - (3 * 86400):
            # and have they not already requested a reset?
            incomplete.append("")
            flash(
                "You have recently requested a password reset and an e-mail has been sent to you containing a reset link. It could take a while to arrive; also, don't forget to check your spam folder.")
        else:
            # okay, send an e-mail
            try:
                resetting_user.email_token(new=False)
                return render_template("error.html", title="Success",
                                       message="An e-mail has been sent to you containing instructions on how to reset your password.")
            except RuntimeError:
                # no e-mail could be sent - clear the token so the user can try again later
                resetting_user.clear_token()
                incomplete.append(username)
                flash("The username was recognised but no reset e-mail could be sent. Please try again later.")

    # show page
    return render_template("account/request-password.html", incomplete=incomplete, flashes=get_flashed_messages(),
                           form=request.form)


@app.route("/dismiss-notification/<int:notification_id>")
def dismiss_notification(notification_id):
    current_user.dismiss_notification(notification_id)

    if not request.args.get("async"):
        redirect_url = request.headers.get("Referer")
        if not redirect_url:
            redirect_url = url_for("show_frontpage")

        return redirect(redirect_url)
    else:
        return jsonify({"success": True})
