"""
4CAT Web Tool views - pages to be viewed by the user
"""
import datetime
import re
import os
import sys
import time
import json
import shlex
import smtplib
import requests
import psycopg2
import markdown2
import subprocess
import packaging.version

import backend
import common.config_manager as config
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import render_template, jsonify, request, abort, flash, get_flashed_messages, url_for, redirect, send_file
from flask_login import login_required, current_user

from webtool import app, db, queue
from webtool.lib.helpers import admin_required, error, Pagination
from webtool.lib.user import User

from common.lib.helpers import call_api, send_email, UserInput, get_github_version
from common.lib.exceptions import QueryParametersException
import common.lib.config_definition as config_definition


@app.route('/admin/', defaults={'page': 1})
@app.route('/admin/page/<int:page>/')
@login_required
@admin_required
def admin_frontpage(page):
    offset = (page - 1) * 20
    filter = request.args.get("filter", "")

    filter_bit = ""
    replacements = []
    if filter:
        filter_bit = "WHERE name LIKE %s"
        replacements = ["%" + filter + "%"]

    num_users = db.fetchone("SELECT COUNT(*) FROM USERS " + filter_bit, replacements)["count"]
    users = db.fetchall(
        "SELECT * FROM users " + filter_bit + "ORDER BY is_admin DESC, name ASC LIMIT 20 OFFSET %i" % offset,
        replacements)
    notifications = db.fetchall("SELECT * FROM users_notifications ORDER BY username ASC, id ASC")
    pagination = Pagination(page, 20, num_users, "admin_frontpage")

    return render_template("controlpanel/frontpage.html", notifications=notifications, users=users,
                           filter={"filter": filter}, pagination=pagination, flashes=get_flashed_messages())


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

    This route is used for the 'approve' link in the e-mail sent when people
    request a new account.

    :return: Either an html page with a message, or a JSON response, depending
    on whether ?format == html
    """
    if not current_user.is_authenticated or not current_user.is_admin:
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

            user = User.get_by_name(db, username)
            if user is None:
                response = {**response, **{"message": "User was created but could not be instantiated properly."}}
            else:
                try:
                    token = user.email_token(new=True)
                    response["success"] = True
                    response = {**response, **{
                        "message": "An e-mail containing a link through which the registration can be completed has "
                                   "been sent to %s.\n\nTheir registration link is [%s](%s)" % (
                                   username, token, token)}}
                except RuntimeError as e:
                    response = {**response, **{
                        "message": "User was created but the registration e-mail could not be sent to them (%s)." % e}}
        except psycopg2.IntegrityError:
            db.rollback()
            if not force:
                response = {**response, **{
                    "message": 'Error: User %s already exists. If you want to re-create the user and re-send the '
                               'registration e-mail, use [this link](/admin/add-user?email=%s&force=1&format=%s).' % (
                                   username, username, fmt)}}
            else:
                # if a user does not use their token in time, maybe you want to
                # be a benevolent admin and give them another change, without
                # having them go through the whole signup again
                user = User.get_by_name(db, username)
                db.update("users", data={"timestamp_token": int(time.time())}, where={"name": username})

                try:
                    url = user.email_token(new=True)
                    response["success"] = True
                    response = {**response, **{
                        "message": "A new registration e-mail has been sent to %s. The registration link is [%s](%s)" % (
                        username, url, url)}}
                except RuntimeError as e:
                    response = {**response, **{
                        "message": "Token was reset but registration e-mail could not be sent (%s)." % e}}

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
    if not current_user.is_authenticated or not current_user.is_admin:
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
            form_answer = Path(config.get('PATH_ROOT'), "webtool/pages/reject-template.md")
            if not form_answer.exists():
                form_message = "No %s 4 u" % config.get("4cat.name")
            else:
                form_message = form_answer.read_text(encoding="utf-8")
                form_message = form_message.replace("{{ name }}", name)
                form_message = form_message.replace("{{ email }}", email_address)

        return render_template("account/reject.html", email=email_address, name=name, message=form_message,
                               incomplete=incomplete)

    message = MIMEMultipart("alternative")
    message["From"] = config.get('NOREPLY_EMAIL')
    message["To"] = email_address
    message["Subject"] = "Your %s account request" % config.get("4cat.name")

    html_message = markdown2.markdown(form_message)
    message.attach(MIMEText(form_message, "plain"))
    message.attach(MIMEText(html_message, "html"))

    try:
        send_email([email_address], message)
    except (smtplib.SMTPException, ConnectionRefusedError) as e:
        return render_template("error.html", message="Could not send e-mail to %s: %s" % (email_address, e),
                               title="Error sending rejection")

    return render_template("error.html", message="Rejection sent to %s." % email_address, title="Rejection sent")


@app.route("/admin/<string:mode>-user/", methods=["GET", "POST"])
@login_required
@admin_required
def manipulate_user(mode):
    """
    Edit or create a user

    :param str mode: Edit an existing user or create a new one?
    :return:
    """
    if not current_user.is_authenticated or not current_user.is_admin:
        return error(403, message="This page is off-limits to you.")

    user_email = request.args.get("name", request.form.get("current-name"))
    if user_email in ("anonymous", "autologin"):
        return error(403, message="System users cannot be edited")

    user = db.fetchone("SELECT * FROM users WHERE name = %s", (user_email,)) if mode == "edit" else {}

    incomplete = []
    if request.method == "POST":
        if not request.form.get("name", request.args.get("name")):
            incomplete.append("name")

        # userdata needs to be valid JSON, or empty
        if request.form.get("userdata"):
            try:
                json.loads(request.form.get("userdata"))
            except ValueError:
                incomplete.append("userdata")

        # names cannot contain whitespace
        if request.form.get("name") and re.findall(r"\s", request.form.get("name")):
            flash("User name cannot contain whitespace.")
            incomplete.append("name")

        if not incomplete:
            user_data = {
                "name": request.form.get("name"),
                "is_admin": request.form.get("is_admin") == "on",
                "is_deactivated": request.form.get("is_deactivated") == "on",
                "userdata": request.form.get("userdata", "").strip()
            }
            if not user_data["userdata"]:
                # it's expected that this parses to a JSON object
                user_data["userdata"] = "{}"

            if mode == "edit":
                db.update("users", where={"name": request.form.get("current-name")}, data=user_data)
                user = request.form
            else:
                try:
                    db.insert("users", user_data)
                    user = User.get_by_name(db, user_data["name"])

                    if request.form.get("password"):
                        user.set_password(request.form.get("password"))
                    else:
                        token = user.generate_token(None, regenerate=True)
                        link = url_for("reset_password", _external=True) + "?token=%s" % token
                        flash('User created. %s can set a password via<br><a href="%s">%s</a>.' % (
                        user_data["name"], link, link))

                    # show the edit form for the user next
                    mode = "edit"
                    user = user.data

                except psycopg2.IntegrityError:
                    flash("A user with this e-mail address already exists.")
                    incomplete.append("name")

            if not incomplete:
                flash("User data saved")
        else:
            flash("Pleasure ensure all fields contain a valid value.")

    return render_template("controlpanel/user.html", user=user, incomplete=incomplete, flashes=get_flashed_messages(),
                           mode=mode)


@app.route("/admin/delete-user")
@login_required
def delete_user():
    """
    Delete a user

    To be implemented - need to figure out which traces of a user to delete...

    :return:
    """
    abort(501, "Deleting users is not possible at the moment")


@app.route("/admin/settings", methods=["GET", "POST"])
@login_required
@admin_required
def update_settings():
    """
    Update 4CAT settings
    """
    definition = config_definition.config_definition
    categories = config_definition.categories
    modules = {
        **{datasource: definition["name"] for datasource, definition in backend.all_modules.datasources.items()},
        **{processor.type: processor.title if hasattr(processor, "title") else processor.type for processor in
           backend.all_modules.processors.values()}
    }

    for processor in backend.all_modules.processors.values():
        if hasattr(processor, "config"):
            definition.update(processor.config)

    if request.method == "POST":
        try:
            new_settings = UserInput.parse_all(definition, request.form.to_dict(),
                                               silently_correct=False)

            for setting, value in new_settings.items():
                valid = config.set_or_create_setting(setting, value,
                                                     raw=definition[setting].get("type") == UserInput.OPTION_TEXT_JSON)
                print("%s: %s" % (setting, repr(valid)))
                if valid is None:
                    flash("Invalid value for %s" % setting)

            flash("Settings saved")
        except QueryParametersException as e:
            flash("Invalid settings: %s" % str(e))

    all_settings = config.get_all()
    options = {}

    for option in sorted({*all_settings.keys(), *definition.keys()}):
        if definition.get(option, {}).get("type") != UserInput.OPTION_TEXT_JSON:
            default = all_settings.get(option, definition.get(option, {}).get("default"))
        else:
            default = json.dumps(all_settings.get(option, definition.get(option, {}).get("default")))

        options[option] = {
            **definition.get(option, {
                "type": UserInput.OPTION_TEXT,
                "help": option,
                "default": all_settings.get(option)
            }),
            "default": default
        }

    return render_template("controlpanel/config.html", options=options, flashes=get_flashed_messages(),
                           categories=categories, modules=modules)


@app.route("/create-notification/", methods=["GET", "POST"])
@login_required
@admin_required
def create_notification():
    """
    Create new notification

    :return:
    """
    incomplete = []
    params = {}
    if request.method == "POST":
        params = request.form.to_dict()

        if not params["notification"]:
            incomplete.append("notification")

        if not params["username"]:
            incomplete.append("username")

        recipient = User.get_by_name(db, params["username"])
        if not recipient and params["username"] not in ("!everyone", "!admins"):
            flash("User '%s' does not exist" % params["username"])
            incomplete.append("username")

        if params["expires"]:
            try:
                expires = int(params["expires"])
            except ValueError:
                incomplete.append("expires")
        else:
            expires = None

        if not incomplete:
            db.insert("users_notifications", {
                "username": params["username"],
                "notification": params["notification"],
                "timestamp_expires": int(time.time() + expires) if expires else None,
                "allow_dismiss": not not params.get("allow_dismiss")}, safe=True)
            flash("Notification added")
            return redirect(url_for("admin_frontpage"))

        else:
            flash("Please ensure all fields contain a valid value.")

    return render_template("controlpanel/add-notification.html", incomplete=incomplete, flashes=get_flashed_messages(),
                           notification=params)


@app.route("/delete-notification/<int:notification_id>")
@login_required
@admin_required
def delete_notification(notification_id):
    """
    Delete notification

    Deletes a notification with the given ID

    :param notification_id:  ID of notification to delete
    :return:
    """
    db.execute("DELETE FROM users_notifications WHERE id = %s", (notification_id,))

    redirect_url = request.headers.get("Referer")
    if not redirect_url:
        redirect_url = url_for("admin_frontpage")

    return redirect(redirect_url)


@app.route("/admin/trigger-restart/", methods=["POST", "GET"])
@login_required
@admin_required
def trigger_restart():
    """
    Trigger a 4CAT upgrade or restart

    Calls the migrate.py script with parameters to make it check out the latest
    4CAT release available from the configured repository, and restart the
    daemon and front-end.

    One issue is that restarting the front-end is not always possible, because
    it depends on how the server is set up. In practice, the 4cat.wsgi file is
    touched, so if the server is set up to reload when that file updates (as is
    common in e.g. mod_wsgi) it should trigger a reload.

    :param str mode:  Restart or upgrade?
    """
    # figure out the versions we are dealing with
    if Path(config.get("PATH_ROOT"), ".current-version").exists():
        current_version = Path(config.get("PATH_ROOT"), ".current-version").open().readline().strip()
    else:
        current_version = "unknown"

    code_version = Path(config.get("PATH_ROOT"), "VERSION").open().readline().strip()
    try:
        github_version = get_github_version()[0]
    except (json.JSONDecodeError, requests.RequestException):
        github_version = "unknown"

    # upgrade is available if we have all info and the release is newer than
    # the currently checked out code
    can_upgrade = not (github_version == "unknown" or code_version == "unknown" or packaging.version.parse(
        current_version) >= packaging.version.parse(github_version))

    if request.method == "POST":
        # run upgrade or restart via shell commands
        mode = request.form.get("action")
        if mode not in ("upgrade", "restart"):
            return "Invalid mode", 400

        # this log file is used to keep track of the progress, and will also
        # be viewable in the web interface
        log_stream = Path(config.get("PATH_ROOT"), config.get("PATH_LOGS"), "restart.log").open("w")

        log_stream.write("%s initiated at server timestamp %s\n" % (mode.title(), datetime.datetime.now().strftime("%c")))
        log_stream.write("Telling 4CAT to %s via job queue...\n" % mode)
        queue.add_job("restart-4cat", {}, mode)

        start_time = time.time()
        backend_log_file = Path(config.get("PATH_ROOT"), config.get("PATH_LOGS"), "restart-backend.log")
        backend_log = []

        timeout = True
        worker_ok = False
        docker_ok = True

        while start_time > time.time() - (10 * 60):  # 10 minutes timeout
            # wait for worker to complete
            time.sleep(0.25)
            if not backend_log_file.exists():
                # give the backend some time
                continue

            with backend_log_file.open() as infile:
                new_lines = infile.read().strip().split("\n")[len(backend_log):]

            if new_lines:
                log_stream.write("\n".join(new_lines) + "\n")
                backend_log.extend(new_lines)
                last_line = new_lines[-1]

                if last_line.startswith("[4CAT] Success"):
                    worker_ok = True
                    timeout = False
                    break
                elif last_line.startswith("[4CAT] Error"):
                    timeout = False
                    break

        if not worker_ok:
            message = "Upgrade and/or restart failed. You may need to restart 4CAT or the container manually."
            flash(message + " See process log for details.")

            if timeout:
                log_stream.write("Timed out waiting for 4CAT to restart.\n")

            log_stream.write(message)

        if worker_ok and mode == "upgrade" and config.get("USING_DOCKER"):
            # if we're in Docker, the front-end container (in which this code
            # runs) will not have upgraded yet! because it uses a separate
            # checked out repository
            # so run the relevant shell commands here as well
            docker_ok = False
            command = sys.executable + " helper-scripts/migrate.py --release --repository %s --yes" % shlex.quote(
                    config.get("4cat.github_url"))

            try:
                response = subprocess.run(shlex.split(command), stdout=log_stream, stderr=subprocess.STDOUT, text=True,
                                          check=True, cwd=config.get("PATH_ROOT"), stdin=subprocess.DEVNULL)
                if response.returncode != 0:
                    raise RuntimeError("Unexpected return code %s" % str(response.returncode))
                docker_ok = True

            except (RuntimeError, subprocess.CalledProcessError) as e:
                # this is bad :(
                flash("%s unsuccessful (%s). Check log files for details. You may need to manually restart 4CAT." % (
                    mode.title(), e))

        if worker_ok and (not config.get("USING_DOCKER") or docker_ok):
            # trigger a Flask reload - many ways to do this...
            # touch the WSGI file, which in some setups will be enough to trigger
            # a reload
            log_stream.write("Attempting to restart front-end...\n")
            wsgi_file = Path(config.get("PATH_ROOT"), "webtool", "4cat.wsgi")
            wsgi_file.touch()
            log_stream.write("Done. %s successful.\n" % mode.title())
            flash("%s successful." % mode.title())

    return render_template("controlpanel/restart.html", flashes=get_flashed_messages(),
                           can_upgrade=can_upgrade, current_version=current_version, tagged_version=github_version)


@app.route("/admin/restart-log/")
@login_required
@admin_required
def restart_log():
    """
    Retrieve the remote restart log file

    Useful to display in the web interface to keep track of how this is going!

    :return:
    """
    log_file = Path(config.get("PATH_ROOT"), config.get("PATH_LOGS"), "restart.log")
    if log_file.exists():
        return send_file(log_file)
    else:
        return "Not Found", 404
