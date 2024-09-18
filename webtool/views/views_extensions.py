"""
4CAT extension views - routes to manipulate 4CAT extensions
"""

from flask import render_template, request, flash, get_flashed_messages
from flask_login import current_user, login_required

from webtool import app, config
from common.lib.helpers import find_extensions

from common.config_manager import ConfigWrapper

config = ConfigWrapper(config, user=current_user, request=request)


@app.route("/admin/extensions/")
@login_required
def extensions_panel():
    extensions, load_errors = find_extensions()

    if extensions is None:
        return render_template("error.html", message="No extensions folder is available - cannot "
                                                         "list or manipulate extensions in this 4CAT server."), 500

    for error in load_errors:
        flash(error)

    return render_template("controlpanel/extensions-list.html", extensions=extensions, flashes=get_flashed_messages())
