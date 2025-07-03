"""
4CAT extension views - routes to manipulate 4CAT extensions
"""

from flask import Blueprint, render_template, flash, get_flashed_messages
from flask_login import login_required

from common.lib.helpers import find_extensions

component = Blueprint("extensions", __name__)

@component.route("/admin/extensions/")
@login_required
def extensions_panel():
    extensions, load_errors = find_extensions()

    if extensions is None:
        return render_template("error.html", message="No extensions folder is available - cannot "
                                                         "list or manipulate extensions in this 4CAT server."), 500

    for error in load_errors:
        flash(error)

    return render_template("controlpanel/extensions-list.html", extensions=extensions, flashes=get_flashed_messages())
