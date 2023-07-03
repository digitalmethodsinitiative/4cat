"""
4CAT Web Tool views - pages to be viewed by the user
"""
import itertools
import markdown2
import datetime
import psycopg2
import smtplib
import time
import json
import os
import re

from pathlib import Path

import backend
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import render_template, jsonify, request, flash, get_flashed_messages, url_for, redirect
from flask_login import current_user, login_required

from webtool import app, db, config
from webtool.lib.helpers import error, Pagination, generate_css_colours, setting_required
from common.lib.user import User

from common.lib.helpers import call_api, send_email, UserInput
from common.lib.exceptions import QueryParametersException
import common.lib.config_definition as config_definition

from common.config_manager import ConfigWrapper
config = ConfigWrapper(config, user=current_user)

@app.route("/admin/")
@login_required
def admin_frontpage():
    # can be viewed if user has any admin privileges
    admin_privileges = config.get([key for key in config.config_definition.keys() if key.startswith("privileges.admin")])

    if not any(admin_privileges.values()):
        return render_template("error.html", message="You cannot view this page."), 403

    # collect some stats
    now = time.time()
    num_items = {
        "day": db.fetchone("SELECT SUM(num_rows) AS num FROM datasets WHERE timestamp > %s", (now - 86400,))["num"],
        "week": db.fetchone("SELECT SUM(num_rows) AS num FROM datasets WHERE timestamp > %s", (now - (86400 * 7),))["num"],
        "overall": db.fetchone("SELECT SUM(num_rows) AS num FROM datasets")["num"]
    }

    num_datasets = {
        "day": db.fetchone("SELECT COUNT(*) AS num FROM datasets WHERE timestamp > %s", (now - 86400,))["num"],
        "week": db.fetchone("SELECT COUNT(*) AS num FROM datasets WHERE timestamp > %s", (now - (86400 * 7),))["num"],
        "overall": db.fetchone("SELECT COUNT(*) AS num FROM datasets")["num"]
    }

    disk_stats = {
        "data": sum([f.stat().st_size for f in config.get("PATH_DATA").glob("**/*") if f.is_file()]),
        "logs": sum([f.stat().st_size for f in config.get("PATH_LOGS").glob("**/*") if f.is_file()]),
        "db": db.fetchone("SELECT pg_database_size(%s) AS num", (config.get("DB_NAME"),))["num"]
    }

    upgrade_available = not not db.fetchone("SELECT * FROM users_notifications WHERE username = '!admins' AND notification LIKE 'A new version of 4CAT%'")

    return render_template("controlpanel/frontpage.html", flashes=get_flashed_messages(), stats = {
        "captured": num_items, "datasets": num_datasets, "disk": disk_stats
    }, upgrade_available=upgrade_available)

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
        filter_bits.append("name LIKE %s")
        replacements.append("%" + filter_name + "%")

    if tag:
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
    workers = call_api("worker-status")["response"]["running"]
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
            db.insert("users", data={"name": username, "timestamp_token": int(time.time()), "timestamp_created": int(time.time())})

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
                db.update("users", data={"password": "", "timestamp_token": int(time.time())}, where={"name": username})

                try:
                    url = user.email_token(new=True)
                    redirect_to_page = True
                    response["success"] = True
                    response = {**response, **{
                        "message": "A new registration e-mail has been sent to %s. The registration link is [%s](%s)" % (
                        username, url, url)}}
                except RuntimeError as e:
                    response = {**response, **{
                        "message": "Token was reset but registration e-mail could not be sent (%s)." % e}}

    if fmt == "html":
        if redirect_to_page:
            flash(response["message"])
            return redirect(url_for("manipulate_user", values={"name": username}))
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
    all_tags = set.union(*[set(user["tags"]) for user in db.fetchall("SELECT tags FROM users")])
    tags = [{"tag": tag, "explicit": True} for tag in tag_priority]
    tags.extend([{"tag": tag, "explicit": False} for tag in all_tags if tag not in tag_priority])

    if not tags:
        # admin tag always exists
        tags = [{"tag": "admin", "explicit": True}]

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
        config.set("flask.tag_order", json.dumps(order))

        # always async
        return jsonify({"success": True})

    return render_template("controlpanel/user-tags.html", tags=tags, flashes=get_flashed_messages())

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
        **{datasource + "-search": definition["name"] for datasource, definition in backend.all_modules.datasources.items()},
        **{processor.type: processor.title if hasattr(processor, "title") else processor.type for processor in
           backend.all_modules.processors.values()}
    }

    global_settings = config.get_all(user=None, tags=None)
    update_css = False

    if request.method == "POST":
        try:
            # this gives us the parsed values, as Python variables, i.e. before
            # potentially encoding them as JSON
            new_settings = UserInput.parse_all(definition, request.form.to_dict(),
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
                    else:
                        print(f"{repr(global_value)} ({type(global_value)}) <> {repr(value)} ({type(value)})")
                        print(f"same: {global_value == value}")
                        print(f"global is not None: {global_value is not None}")

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

        options[option] = {
            **definition.get(option, {
                "type": UserInput.OPTION_TEXT,
                "help": option,
                "default": all_settings.get(option)
            }),
            "default": default,
            "is_changed": is_changed
        }

        if tag and is_changed:
            changed_categories.add(option.split(".")[0])

    tab = "" if not request.form.get("current-tab") else request.form.get("current-tab")

    datasources = {
        datasource: {
            **info,
            "enabled": datasource in config.get("datasources.enabled"),
            "expires": config.get("datasources.expiration").get(datasource, {})
        }
        for datasource, info in backend.all_modules.datasources.items()}

    return render_template("controlpanel/config.html", options=options, flashes=get_flashed_messages(),
                           categories=categories, modules=modules, tag=tag, current_tab=tab,
                           datasources_config=datasources, changed=changed_categories)

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


