"""
4CAT extension views - routes to manipulate 4CAT extensions
"""
import re

from flask import render_template, request, flash, get_flashed_messages, redirect, url_for
from flask_login import current_user, login_required

from webtool import app, config, queue
from webtool.lib.helpers import setting_required
from common.lib.helpers import find_extensions

from common.config_manager import ConfigWrapper

config = ConfigWrapper(config, user=current_user, request=request)


@app.route("/admin/extensions/", methods=["GET", "POST"])
@login_required
@setting_required("privileges.admin.can_manage_extensions")
def extensions_panel():
    extensions, load_errors = find_extensions()

    if extensions is None:
        return render_template("error.html", message="No extensions folder is available - cannot "
                                                     "list or manipulate extensions in this 4CAT server."), 500

    incomplete = []
    if request.method == "POST":
        install_started = True

        if request.files["extension-file"].filename:
            uploaded_file = request.files["extension-file"]
            stem = re.sub(r"[^a-zA-Z0-9_-]", "", uploaded_file.filename.replace(" ", "_")).strip()
            temporary_path = config.get("PATH_ROOT").joinpath("extensions").joinpath(f"temp-{stem}.zip")
            uploaded_file.save(temporary_path)
            queue.add_job("manage-extension", details={"task": "install", "source": "local"},
                          remote_id=str(temporary_path))
            extension_reference = uploaded_file.filename

        else:
            extension_reference = request.form.get("extension-url")
            if extension_reference:
                queue.add_job("manage-extension", details={"task": "install", "source": "remote"},
                              remote_id=extension_reference)
            else:
                install_started = False
                flash("You need to provide either a repository URL or zip file to install an extension.")
                incomplete.append("extension-url")

        if install_started:
            flash(f"Initiated extension install from {extension_reference}. Find its status in the panel at the bottom "
                  f"of the page. You may need to refresh the page after installation completes.")

    for error in load_errors:
        flash(error)

    return render_template("controlpanel/extensions-list.html", extensions=extensions,
                           flashes=get_flashed_messages(), incomplete=incomplete)


@app.route("/admin/uninstall-extension", methods=["POST"])
@login_required
@setting_required("privileges.admin.can_manage_extensions")
def uninstall_extension():
    extensions, load_errors = find_extensions()

    extension_reference = request.form.get("extension-name")

    if not extensions or not extension_reference or extension_reference not in extensions:
        flash(f"Extension {extension_reference} unknown - cannot uninstall extension.")
    else:
        queue.add_job("manage-extension", details={"task": "uninstall"},
                      remote_id=extension_reference)

        flash(f"Initiated uninstall of extension '{extension_reference}'. Find its status in the panel at the bottom "
              f"of the page. You may need to refresh the page afterwards.")

    return redirect(url_for("extensions_panel"))