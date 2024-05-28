"""
4CAT Web Tool views - pages to be viewed by the user
"""
import markdown2
import datetime
import psycopg2
import psycopg2.errors
import tailer
import smtplib
import time
import json
import csv
import io
import re

from pathlib import Path
from dateutil.parser import parse as parse_datetime, ParserError

import backend
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import render_template, jsonify, request, flash, get_flashed_messages, url_for, redirect, Response
from flask_login import current_user, login_required

from webtool import app, db, config
from webtool.lib.helpers import error, Pagination, generate_css_colours, setting_required
from common.lib.user import User
from common.lib.dataset import DataSet

from common.lib.helpers import call_api, send_email, UserInput, folder_size
from common.lib.helpers import call_api, send_email, UserInput, folder_size, get_git_branch
from common.lib.exceptions import QueryParametersException
import common.lib.config_definition as config_definition

from common.config_manager import ConfigWrapper

config = ConfigWrapper(config, user=current_user, request=request)


@app.route("/admin/")
@login_required
def admin_frontpage():
    # can be viewed if user has any admin privileges
    admin_privileges = config.get(
        [key for key in config.config_definition.keys() if key.startswith("privileges.admin")])

    if not any(admin_privileges.values()):
        return render_template("error.html", message="You cannot view this page."), 403

    # collect some stats
    now = time.time()
    num_items = {
        "day": db.fetchone("SELECT SUM(num_rows) AS num FROM datasets WHERE timestamp > %s AND key_parent = '' AND (type LIKE '%%-search' OR type LIKE '%%-import')", (now - 86400,))["num"],
        "week": db.fetchone("SELECT SUM(num_rows) AS num FROM datasets WHERE timestamp > %s AND key_parent = '' AND (type LIKE '%%-search' OR type LIKE '%%-import')", (now - (86400 * 7),))[
            "num"],
        "overall": db.fetchone("SELECT SUM(num_rows) AS num FROM datasets WHERE key_parent = '' AND (type LIKE '%%-search' OR type LIKE '%%-import')")["num"]
    }

    num_datasets = {
        "day": db.fetchone("SELECT COUNT(*) AS num FROM datasets WHERE timestamp > %s", (now - 86400,))["num"],
        "week": db.fetchone("SELECT COUNT(*) AS num FROM datasets WHERE timestamp > %s", (now - (86400 * 7),))["num"],
        "overall": db.fetchone("SELECT COUNT(*) AS num FROM datasets")["num"]
    }

    disk_stats = {
        "data": db.fetchone("SELECT count FROM metrics WHERE datasource = '4cat' AND metric = 'size_data'"),
        "logs": db.fetchone("SELECT count FROM metrics WHERE datasource = '4cat' AND metric = 'size_logs'"),
        "db": db.fetchone("SELECT count FROM metrics WHERE datasource = '4cat' AND metric = 'size_db'"),
    }

    # it is possible these stats don't exist yet, so replace with 0 if that is the case
    disk_stats = {k: v["count"] if v else 0 for k, v in disk_stats.items()}

    upgrade_available = not not db.fetchone(
        "SELECT * FROM users_notifications WHERE username = '!admin' AND notification LIKE 'A new version of 4CAT%'")

    tags = config.get_active_tags(current_user)
    current_branch = get_git_branch()
    return render_template("controlpanel/frontpage.html", flashes=get_flashed_messages(), stats={
        "captured": num_items, "datasets": num_datasets, "disk": disk_stats
    }, upgrade_available=upgrade_available, tags=tags, current_branch=current_branch)


@app.route("/admin/users/", defaults={"page": 1})
@app.route("/admin/users/page/<int:page>/")
@login_required
@setting_required("privileges.admin.can_manage_users")
def list_users(page):
    """
    List users

    :param int page:
    """
    page_size = 25
    tag = request.args.get("tag", "")
    offset = (page - 1) * page_size
    filter_name = request.args.get("name", "")
    order = request.args.get("sort", "name")

    # craft SQL query to filter users with
    filter_bits = []
    replacements = []
    if filter_name:
        filter_bits.append("(name ILIKE %s OR userdata::json->>'notes' ILIKE %s)")
        replacements.append("%" + filter_name + "%")
        replacements.append("%" + filter_name + "%")

    if tag:
        if tag.startswith("user:"):
            filter_bits.append("name LIKE %s")
            replacements.append(re.sub("^user:", "", tag))
        else:
            filter_bits.append("tags != '[]' AND tags @> %s")
            replacements.append('["' + tag + '"]')

    filter_bit = "WHERE " + (" AND ".join(filter_bits)) if filter_bits else ""
    order_bit = "name ASC"
    if order == "age":
        order_bit = "timestamp_created ASC"
    elif order == "status":
        order_bit = "tags @> '[\"admin\"]' DESC, timestamp_token > 0 DESC, is_deactivated DESC"

    num_users = db.fetchone("SELECT COUNT(*) AS num FROM users " + filter_bit, replacements)["num"]
    users = db.fetchall(
        f"SELECT * FROM users {filter_bit} ORDER BY {order_bit} LIMIT {page_size} OFFSET {offset}",
        replacements)

    # these are used for autocompletion in the filter form
    distinct_tags = set.union(*[set(u["tags"]) for u in db.fetchall("SELECT DISTINCT tags FROM users")])
    distinct_users = [u["name"] for u in db.fetchall("SELECT DISTINCT name FROM users")]

    pagination = Pagination(page, page_size, num_users, "list_users")
    return render_template("controlpanel/users.html", users=[User(db, user) for user in users],
                           filter={"tag": tag, "name": filter_name, "sort": order}, pagination=pagination,
                           flashes=get_flashed_messages(), tag=tag, all_tags=distinct_tags, all_users=distinct_users)


@app.route("/admin/worker-status/")
@login_required
@setting_required("privileges.admin.can_view_status")
def get_worker_status():
    workers = [
        {
            **worker,
            "dataset": None if not worker["dataset_key"] else DataSet(key=worker["dataset_key"], db=db)
        } for worker in call_api("worker-status")["response"]["running"]
    ]
    return render_template("controlpanel/worker-status.html", workers=workers, worker_types=backend.all_modules.workers,
                           now=time.time())


@app.route("/admin/queue-status/")
@login_required
@setting_required("privileges.admin.can_view_status")
def get_queue_status():
    queue = call_api("worker-status")["response"]["queued"]
    return render_template("controlpanel/queue-status.html", queue=queue, worker_types=backend.all_modules.workers,
                           now=time.time())


@app.route("/admin/add-user/")
@login_required
@setting_required("privileges.admin.can_manage_users")
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
    response = {"success": False}

    email = request.form.get("email", request.args.get("email", "")).strip()
    fmt = request.form.get("format", request.args.get("format", "")).strip()
    force = request.form.get("force", request.args.get("force", None))
    redirect_to_page = False

    if not email or not re.match(r"[^@]+\@.*?\.[a-zA-Z]+", email):
        response = {**response, **{"message": "Please provide a valid e-mail address."}}
    else:
        username = email
        try:
            db.insert("users", data={"name": username, "timestamp_token": int(time.time()),
                                     "timestamp_created": int(time.time())})

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
        except (psycopg2.IntegrityError, psycopg2.errors.UniqueViolation):
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
                db.update("users", data={"password": "", "timestamp_token": int(time.time())}, where={"name": username})

                try:
                    url = user.email_token(new=True)
                    redirect_to_page = True
                    response["success"] = True
                    response = {**response, **{
                        "message": "A new registration e-mail has been sent to %s. The registration link is [%s](%s)" % (
                            username, url, url)}}
                except RuntimeError as e:
                    # Grab the token and provide it to the admin, so they can send to user
                    new_token = user.generate_token()
                    url_base = config.get("flask.server_name")
                    protocol = "https" if config.get("flask.https") else "http"
                    url = "%s://%s/reset-password/?token=%s" % (protocol, url_base, new_token)
                    response = {**response, **{
                        "message": "Token was reset but registration e-mail could not be sent (%s). Reset password link: [%s](%s)" % (e, url, url)}}

    if fmt == "html":
        if redirect_to_page:
            flash(response["message"])
            return redirect(url_for("manipulate_user", mode="edit", name=username))
        else:
            return render_template("error.html", message=response["message"],
                                   title=("New account created" if response["success"] else "Error"))
    else:
        return jsonify(response)


@app.route("/admin/reject-user/", methods=["GET", "POST"])
@login_required
@setting_required("privileges.admin.can_manage_users")
def reject_user():
    """
    (Politely) reject an account request

    Sometimes, account requests need to be rejected. If you want to let the
    requester know of the rejection, this is the route to use :-)

    :return: HTML form, or message containing the e-mail send status
    """
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
            form_answer = Path(config.get("PATH_ROOT"), "webtool/pages/reject-template.md")
            if not form_answer.exists():
                form_message = "No %s 4 u" % config.get("4cat.name")
            else:
                form_message = form_answer.read_text(encoding="utf-8")
                form_message = form_message.replace("{{ name }}", name)
                form_message = form_message.replace("{{ email }}", email_address)

        return render_template("account/reject.html", email=email_address, name=name, message=form_message,
                               incomplete=incomplete)

    message = MIMEMultipart("alternative")
    message["From"] = config.get("mail.noreply")
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


@app.route("/admin/delete-user", methods=["POST"])
@login_required
@setting_required("privileges.admin.can_manage_users")
def delete_user():
    """
    Delete a user

    :return:
    """
    username = request.form.get("name")
    user = User.get_by_name(db=db, name=username)
    if not username:
        return render_template("error.html", message=f"User {username} does not exist.",
                               title="User not found"), 404

    if user.is_special:
        return render_template("error.html", message=f"User {username} cannot be deleted.",
                               title="User cannot be deleted"), 403

    if user.get_id() == current_user.get_id():
        return render_template("error.html", message=f"You cannot delete your own account.",
                               title="User cannot be deleted"), 403

    # first delete favourites and notifications and api tokens
    user.delete()

    flash(f"User {username} and their datasets have been deleted.")
    return redirect(url_for("admin_frontpage"))


@app.route("/admin/<string:mode>-user/", methods=["GET", "POST"])
@login_required
@setting_required("privileges.admin.can_manage_users")
def manipulate_user(mode):
    """
    Edit or create a user

    :param str mode: Edit an existing user or create a new one?
    :return:
    """
    user_email = request.args.get("name", request.form.get("current-name"))
    if user_email in ("anonymous", "autologin"):
        return error(403, message="System users cannot be edited")

    user = User.get_by_name(db, request.args.get("name")) if mode == "edit" else {}
    if user is None:
        return error(404, message="User not found")

    incomplete = []
    if request.method == "POST":
        if not request.form.get("name", request.args.get("name")):
            incomplete.append("name")

        # names cannot contain whitespace
        if request.form.get("name") and re.findall(r"\s", request.form.get("name")):
            flash("User name cannot contain whitespace.")
            incomplete.append("name")

        # ensure there is always at least one admin user
        old_tags = user.tags if user else []
        new_tags = [re.sub(r"[^a-z0-9_]", "", t.strip().lower()) for t in request.form.get("tags", "").split(",")]
        if "admin" in old_tags and "admin" not in new_tags:
            admin_users = db.fetchall("SELECT name FROM users WHERE tags @> '[\"admin\"]'")
            if len(admin_users) == 1:
                # one admin user that would no longer be an admin - not OK
                flash("There always needs to be at least one user with the 'admin' tag.")
                incomplete.append("tags")

        if not incomplete:
            user_data = {
                "name": request.form.get("name"),
                "is_deactivated": request.form.get("is_deactivated") == "on",
                "tags": json.dumps(new_tags)
            }

            if mode == "edit":
                db.update("users", where={"name": request.form.get("current-name")}, data=user_data)
                user = User.get_by_name(db, user_data["name"])  # ensure updated data

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

                except psycopg2.IntegrityError:
                    flash("A user with this e-mail address already exists.")
                    incomplete.append("name")
                    db.rollback()

            if not incomplete and "autodelete" in request.form:
                autodelete = request.form.get("autodelete").replace("T", " ")[:16]
                if not autodelete:
                    user.set_value("delete-after", "")

                elif not re.match("[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}", autodelete):
                    incomplete.append("autodelete")
                    flash("'Delete after' date must be in YYYY-MM-DD hh:mm format")

                else:
                    autodelete = datetime.datetime.strptime(autodelete, "%Y-%m-%d %H:%M")
                    # I fucking hate timezones
                    autodelete = autodelete.replace(tzinfo=datetime.timezone.utc)
                    user.set_value("delete-after", int(autodelete.timestamp()))

            if not incomplete and request.form.get("notes"):
                user.set_value("notes", request.form.get("notes"))

            if not incomplete:
                user.sort_user_tags()
                flash("User data saved")
        else:
            flash("Pleasure ensure all fields contain a valid value.")

    return render_template("controlpanel/user.html", user=user, incomplete=incomplete, flashes=get_flashed_messages(),
                           mode=mode)


@app.route("/admin/user-tags/", methods=["GET", "POST"])
@login_required
@setting_required("privileges.admin.can_manage_tags")
def manipulate_tags():
    tag_priority = config.get("flask.tag_order")

    # explicit tags are already ordered; implicit tags have not been given a
    # place in the order yet, but are used for at least one user
    all_tags = set.union(
        *[set(user["tags"]) for user in db.fetchall("SELECT tags FROM users")],
        set([setting["tag"] for setting in db.fetchall("SELECT DISTINCT tag FROM settings") if setting["tag"]]))

    tags = [{"tag": tag, "explicit": True} for tag in tag_priority]
    tags.extend([{"tag": tag, "explicit": False} for tag in all_tags if tag not in tag_priority])

    if not [tag for tag in tags if tag["tag"] == "admin"]:
        # admin tag always exists
        tags.append({"tag": "admin", "explicit": True})

    num_admins = 0
    for i, tag in enumerate(tags):
        tags[i]["users"] = db.fetchone("SELECT COUNT(*) AS count FROM users WHERE tags != '[]' AND tags @> %s", ('["' + tag["tag"] + '"]',))["count"]
        if tag["tag"] == "admin":
            num_admins = tags[i]["users"]
        elif tag["tag"].startswith("user:"):
            tags[i]["users"] = 1  # by definition

    if request.method == "POST":
        try:
            # no empty tags
            order = [tag for tag in request.form.get("order", "").split(",") if tag.strip()]
            if not order:
                raise ValueError
        except (TypeError, ValueError):
            return error(406, message="Tag order required")

        # ensure admin is always first in the list
        if "admin" in order and order.index("admin") != 0:
            order.remove("admin")

        if "admin" not in order:
            order.insert(0, "admin")

        # update tags for each user
        # this means we can just use the tags saved for the user directly
        # instead of having to cross-reference with the tag order value, at the
        # expense of some overhead when sorting tags (but that should not
        # happen often)
        tagged_users = db.fetchall("SELECT name, tags FROM users WHERE tags != '{}'")

        for user in tagged_users:
            sorted_tags = []
            for tag in order:
                if tag in user["tags"]:
                    sorted_tags.append(tag)

            db.update("users", where={"name": user["name"]}, data={"tags": json.dumps(sorted_tags)}, commit=False)

        db.commit()

        # save global order, too
        config.set("flask.tag_order", order, tag="")

        # always async
        return jsonify({"success": True})

    return render_template("controlpanel/user-tags.html", tags=tags, num_admins=num_admins, flashes=get_flashed_messages())


@app.route("/admin/settings", methods=["GET", "POST"])
@login_required
@setting_required("privileges.admin.can_manage_settings")
def manipulate_settings():
    """
    Update 4CAT settings
    """
    tag = request.args.get("tag", "")

    definition = config.config_definition
    categories = config_definition.categories

    modules = {
        **{datasource + "-search": definition["name"] for datasource, definition in
           backend.all_modules.datasources.items()},
        **{processor.type: processor.title if hasattr(processor, "title") else processor.type for processor in
           backend.all_modules.processors.values()}
    }

    global_settings = config.get_all(user=None, tags=None)
    update_css = False

    if request.method == "POST":
        try:
            # this gives us the parsed values, as Python variables, i.e. before
            # potentially encoding them as JSON
            new_settings = UserInput.parse_all(definition, request.form,
                                               silently_correct=False)

            for setting, value in new_settings.items():
                if tag:
                    # don't override global settings on a tag level
                    if definition.get(setting, {}).get("global"):
                        continue

                    # admin is a special tag that always has all admin privileges
                    if tag == "admin" and setting.startswith("privileges.admin"):
                        continue

                    # global_settings has the values in 'raw' format, i.e. as
                    # stored in the database, i.e. as JSON
                    global_value = global_settings.get(setting)

                    # only update if value is not the same as global config
                    # else remove override, so if the global changes the tag
                    # isn't stuck in history
                    # if None, the value is not set explicitly, so whatever has
                    # been set here is different (because it is explicit) for now
                    #
                    # so here we compare the JSON from global_settings to the
                    # parsed value, encoded as JSON
                    if global_value == value and global_value is not None:
                        config.delete_for_tag(setting, tag)
                        continue

                valid = config.set(setting, value, tag=tag)

                if valid is None:
                    flash("Invalid value for %s" % setting)
                    continue

                if definition.get(setting, {}).get("type") == UserInput.OPTION_HUE:
                    update_css = True

            if update_css:
                generate_css_colours(force=True)

            flash("Settings saved")
        except QueryParametersException as e:
            flash("Invalid settings: %s" % str(e))

    all_settings = config.get_all(user=None, tags=[tag])
    options = {}

    changed_categories = set()
    for option in sorted({*all_settings.keys(), *definition.keys()}):
        tag_value = all_settings.get(option, definition.get(option, {}).get("default"))
        global_value = global_settings.get(option, definition.get(option, {}).get("default"))
        is_changed = tag and global_value != tag_value

        default = all_settings.get(option, definition.get(option, {}).get("default"))
        if definition.get(option, {}).get("type") == UserInput.OPTION_TEXT_JSON:
            default = json.dumps(default)

        # this is used for organising things in the UI
        option_owner = option.split(".")[0]
        submenu = "other"
        if option_owner in ("4cat", "datasources", "privileges", "path", "mail", "explorer", "flask",
                                    "logging", "ui"):
            submenu = "core"
        elif option_owner.endswith("-search"):
            submenu = "datasources"
        elif option_owner in backend.all_modules.processors:
            submenu = "processors"

        tabname = config_definition.categories.get(option_owner)
        if not tabname:
            tabname = modules.get(option_owner)
        if not tabname:
            tabname = option_owner

        options[option] = {
            **definition.get(option, {
                "type": UserInput.OPTION_TEXT,
                "help": option,
                "default": all_settings.get(option)
            }),
            "submenu": submenu,
            "default": default,
            "tabname": tabname,
            "is_changed": is_changed
        }

        if tag and is_changed:
            changed_categories.add(option.split(".")[0])

    tab = "" if not request.form.get("current-tab") else request.form.get("current-tab")
    options = {k: options[k] for k in sorted(options, key=lambda o: options[o]["tabname"])}

    # 'data sources' is one setting but we want to be able to indicate
    # overrides per sub-item
    expire_override = []
    if all_settings.get("datasources.expiration") and global_settings.get("datasources.expiration"):
        expire_override = [datasource for datasource, settings in all_settings["datasources.expiration"].items() if
                           settings != global_settings["datasources.expiration"].get(datasource)]

    datasources = {
        datasource: {
            **info,
            "enabled": datasource in config.get("datasources.enabled"),
            "expires": config.get("datasources.expiration").get(datasource, {})
        }
        for datasource, info in backend.all_modules.datasources.items()}

    return render_template("controlpanel/config.html", options=options, flashes=get_flashed_messages(),
                           categories=categories, modules=modules, tag=tag, current_tab=tab,
                           datasources_config=datasources, changed=changed_categories,
                           expire_override=expire_override)


@app.route("/manage-notifications/", methods=["GET", "POST"])
@login_required
@setting_required("privileges.admin.can_manage_notifications")
def manipulate_notifications():
    """
    Create new notification

    :return:
    """
    incomplete = []
    notification = {}

    if request.method == "POST":
        params = request.form.to_dict()

        if not params["notification"]:
            incomplete.append("notification")

        if not params["username"]:
            incomplete.append("username")

        recipient = User.get_by_name(db, params["username"])
        if not recipient and not params["username"].startswith("!"):
            flash("User '%s' does not exist" % params["username"])
            incomplete.append("username")

        if params["expires"]:
            try:
                expires = int(params["expires"])
            except ValueError:
                incomplete.append("expires")
        else:
            expires = None

        notification = {
            "username": params.get("username"),
            "notification": params.get("notification"),
            "timestamp_expires": int(time.time() + expires) if expires else None,
            "allow_dismiss": not not params.get("allow_dismiss")
        }

        if not incomplete:
            db.insert("users_notifications", notification, safe=True)
            flash("Notification added")

        else:
            flash("Please ensure all fields contain a valid value.")

    notifications = db.fetchall("SELECT * FROM users_notifications ORDER BY username ASC, id ASC")
    return render_template("controlpanel/notifications.html", incomplete=incomplete, flashes=get_flashed_messages(),
                           notification=notification, notifications=notifications)


@app.route("/delete-notification/<int:notification_id>")
@login_required
@setting_required("privileges.admin.can_manage_notifications")
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


@app.route("/logs/")
@login_required
@setting_required("privileges.admin.can_view_status")
def view_logs():
    """
    Log file overview

    :return:
    """
    return render_template("controlpanel/logs.html")


@app.route("/logs/<string:logfile>/")
@login_required
@setting_required("privileges.admin.can_view_status")
def get_log(logfile):
    """
    Get last lines of log file

    Returns the tail end of a log file.

    :param str logfile: 'backend' or 'stderr'
    :return:
    """
    if logfile not in ("stderr", "backend", "import"):
        return "Not Found", 404

    if logfile == "backend":
        filename = "4cat.log" if not config.get("USING_DOCKER") else "backend_4cat.log"
    elif logfile == "stderr":
        filename = "4cat.stderr"
    else:
        filename = f"{logfile}.log"

    log_file = config.get("PATH_ROOT").joinpath(config.get("PATH_LOGS")).joinpath(filename)
    if log_file.exists():
        with log_file.open() as infile:
            return "\n".join(tailer.tail(infile, 250))
    else:
        return ""


@app.route("/user-bulk", methods=["GET", "POST"])
@login_required
@setting_required("privileges.admin.can_manage_users")
def user_bulk():
    """
    Create many users at once

    Useful if one wants to e.g. import users from elsewhere
    """
    incomplete = []

    if request.method == "POST" and request.files:
        # handle the CSV file
        # sniff the dialect, because it's CSV, so who knows what format it's in
        file = io.TextIOWrapper(request.files["datafile"])
        sample = file.read(3 * 1024)  # 3kB should be enough
        dialect = csv.Sniffer().sniff(sample, delimiters=(",", ";", "\t"))
        file.seek(0)
        reader = csv.DictReader(file, dialect=dialect)

        # keep track of what we read from the file
        prospective_users = []
        dupes = []
        failed_rows = []
        mail_fail = False
        row_index = 1

        # use while True instead of looping through the reader directly,
        # because that way we can catch read errors for individual lines
        while True:
            try:
                row = next(reader)
                if "name" not in row:
                    # the one required column
                    raise ValueError()
                else:
                    prospective_users.append(row)

            except ValueError:
                failed_rows.append(row_index)
                continue

            except StopIteration:
                break

        # OK, we have the users with enough data, now add them one by one
        success = 0
        if prospective_users:
            for user in prospective_users:
                # prevent duplicate users
                exists = db.fetchone("SELECT name FROM users WHERE name = %s", (user["name"],))
                if exists:
                    dupes.append(user["name"])
                    continue

                # only insert with username - other properties are set through
                # the object
                db.insert("users", {"name": user["name"], "timestamp_created": int(time.time())})
                user_obj = User.get_by_name(db, user["name"])

                if user.get("expires"):
                    try:
                        # expiration date needs to be a parseable timestamp
                        # note that we do not check if it is in the future!
                        expires_after = parse_datetime(user["expires"])
                        user_obj.set_value("delete-after", int(expires_after.timestamp()))
                    except (OverflowError, ParserError):
                        # delete the already created user because we have bad
                        # data, and continue with the next one
                        failed_rows.append(user.get("name"))
                        user_obj.delete()
                        continue

                if user.get("password"):
                    user_obj.set_password(user["password"])

                elif config.get("mail.server") and not mail_fail and "@" in user.get("name"):
                    # can send a registration e-mail, but only if the name is
                    # an email address and we have a mail server
                    try:
                        user_obj.email_token(new=True)
                    except RuntimeError as e:
                        mail_fail = str(e)

                if user.get("tags"):
                    for tag in user["tags"].split(","):
                        user_obj.add_tag(tag.strip())

                if user.get("notes"):
                    user_obj.set_value("notes", user.get("notes"))

                success += 1

            flash(f"{success} user(s) were created.")

        # and now we have some specific errors to output if anything went wrong
        else:
            flash("No valid rows in user file, no users added.")

        if dupes:
            flash(f"The following users were skipped because the username already exists: {', '.join(dupes)}.")

        if mail_fail:
            flash(f"E-mails were not sent ({mail_fail}).")

        if failed_rows and prospective_users:
            flash(f"The following rows were skipped because the data in them was invalid: {', '.join([str(r) for r in failed_rows])}.")

    return render_template("controlpanel/user-bulk.html", flashes=get_flashed_messages(),
                           incomplete=incomplete)


@app.route("/dataset-bulk/", methods=["GET", "POST"])
@login_required
@setting_required("privileges.admin.can_manipulate_all_datasets")
def dataset_bulk():
    """
    Manipulate many datasets at once

    Useful to e.g. make sure datasets will not expire, or to make all datasets
    eligible for expiration.
    """
    incomplete = []
    forminput = {}
    datasources = {datasource: meta["name"] for datasource, meta in backend.all_modules.datasources.items()}

    if request.method == "POST":
        # action depends on which button was clicked
        action = [key for key in request.form if key.startswith("action-")]
        if not action:
            flash("Invalid action")
            incomplete.append("action")
        else:
            action = action[0].split("-")[-1]

        where = []
        replacements = []
        forminput = request.form.to_dict()

        # convert date range to timestamps
        try:
            forminput["filter_date_from"] = datetime.datetime.strptime(forminput["filter_date_from"], "%Y-%m-%d").timestamp() if forminput.get("filter_date_from") else None
            forminput["filter_date_to"] = datetime.datetime.strptime(forminput["filter_date_to"], "%Y-%m-%d").timestamp() if forminput.get("filter_date_to") else None
        except (TypeError, ValueError):
            flash("When filtering by date, dates should be in YYYY-mm-dd format.")
            incomplete.append("filter-date")

        # construct SQL filter for datasets
        if forminput.get("filter_name"):
            where.append("key IN ( SELECT key FROM datasets_owners WHERE name LIKE %s AND key = datasets.key)")
            replacements.append(forminput.get("filter_name").replace("*", "%"))

        if forminput.get("filter_date_from"):
            where.append("timestamp >= %s")
            replacements.append(forminput.get("filter_date_from"))

        if forminput.get("filter_date_to"):
            where.append("timestamp < %s")
            replacements.append(forminput.get("filter_date_to"))

        if forminput.get("filter_datasource"):
            forminput["filter_datasource"] = request.form.getlist("filter_datasource")
            where.append("parameters::json->>'datasource' IS NOT NULL AND parameters::json->>'datasource' IN %s")
            replacements.append(tuple(forminput["filter_datasource"]))

        datasets_meta = db.fetchall(f"SELECT * FROM datasets {'WHERE' if where else ''} {' AND '.join(where)}",
                                    tuple(replacements))

        if not datasets_meta:
            flash("No datasets match these criteria")
            incomplete.append("filter")

        if action == "owner":
            # this one is a bit special because we need to figure out if the
            # owners are legitimate (tags are not checked)
            bulk_owner = request.form.get("bulk-owner").replace("*", "%")
            if not bulk_owner:
                flash("Please enter a user or tag to add as owner")
                incomplete.append("bulk-owner")

            if not bulk_owner.startswith("tag:"):
                users = db.fetchall("SELECT name FROM users WHERE name LIKE %s", (bulk_owner,))
                if not users:
                    flash("No users match that username")
                    incomplete.append("bulk-owner")
                else:
                    bulk_owner = [user["name"] for user in users]
            else:
                bulk_owner = [bulk_owner]

            flash(f"{len(bulk_owner):,} new owner(s) were added to the datasets.")

        if not incomplete:
            datasets = [DataSet(data=dataset, db=db) for dataset in datasets_meta]
            flash(f"{len(datasets):,} dataset(s) updated.")

            if action == "export":
                # export dataset metadata as a CSV file, basically a dataset
                # table dump
                def generate_csv(data):
                    """
                    Stream a CSV as a Flask response
                    """
                    buffer = io.StringIO()
                    writer = None
                    for item in data:
                        if not writer:
                            writer = csv.DictWriter(buffer, fieldnames=item.keys())
                            writer.writeheader()
                        writer.writerow(item)
                        buffer.seek(0)
                        yield buffer.read()
                        buffer.truncate(0)
                        buffer.seek(0)

                response = Response(generate_csv(datasets_meta), mimetype="text/csv")
                exporttime = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
                response.headers["Content-Disposition"] = f"attachment; filename=dataset-export-{exporttime}.csv"
                return response

            else:
                for dataset in datasets:
                    if action == "keep":
                        dataset.keep = True

                    if action == "unkeep":
                        dataset.delete_parameter("keep")

                    if action == "delete":
                        dataset.delete()

                    if action == "public":
                        dataset.is_private = False

                    if action == "private":
                        dataset.is_private = True

                    if action == "owner":
                        for user_or_tag in bulk_owner:
                            dataset.add_owner(user_or_tag)

    return render_template("controlpanel/dataset-bulk.html", flashes=get_flashed_messages(),
                           incomplete=incomplete, form=forminput, datasources=datasources)

def import_dataset_from():
    """
    Validate custom data input

    Confirms that the uploaded file is a valid CSV or tab file and, if so, returns
    some metadata.

    :param dict query:  Query parameters, from client-side.
    :param request:  Flask request
    :param User user:  User object of user who has submitted the query
    :return dict:  Safe query parameters
    """
    urls = query.get("url")
    if not urls:
        return QueryParametersException("Provide at least one dataset URL.")

    urls = urls.split(",")
    bases = set([url.split("/results/")[0].lower() for url in urls])
    keys = [url.split("/results/")[-1].split("/")[0].split("#")[0].split("?")[0] for url in urls]
    if len(bases) != 1:
        return QueryParametersException("All URLs need to point to the same 4CAT server. You can only import from "
                                        "one 4CAT server at a time.")

    base = urls[0].split("/results/")[0]
    try:
        test = SearchImportFromFourcat.fetch_from_4cat(base, keys[0], query.get("api-key"), "metadata")
    except FourcatImportException as e:
        raise QueryParametersException(str(e))

    try:
        metadata = test.json()
    except ValueError:
        raise QueryParametersException(f"Unexpected response when trying to fetch metadata for dataset {keys[0]}.")

    version_file = config.get("PATH_ROOT", user=user).joinpath("config/.current-version")
    with version_file.open() as infile:
        version = infile.readline().strip()

    if metadata.get("version") != version:
        raise QueryParametersException("This 4CAT server is running a different version of 4CAT ({version}) than "
                                       "the one you are trying to import from ({metadata.get('version')}). Make "
                                       "sure both are running the same version of 4CAT and try again.")

    # OK, we can import at least one dataset
    return {
        "url": ",".join(urls),
        "api-key": query.get("api-key")
    }
