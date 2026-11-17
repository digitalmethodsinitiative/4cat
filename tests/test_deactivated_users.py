"""
Tests that a deactivated user cannot use 4CAT

The check is a hook in `webtool/views/views_user.py`. It once ran only for the
routes of that file's own blueprint, so a deactivated user could use every
other page, but got a 403 when trying to log out. These tests register the
real `user` blueprint on a small Flask app, next to a stand-in for any other
page, and check that a deactivated user is logged out wherever they go.

Importing the `webtool` package would start the whole web tool (it runs the
first-run script and connects to the database), so an empty stand-in package
takes its place while the view module is loaded.
"""
import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from flask import Blueprint, Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager

USERS = {
	"active@example.com": {"name": "active@example.com", "tags": [], "userdata": "{}", "is_deactivated": False},
	"deactivated@example.com": {"name": "deactivated@example.com", "tags": [], "userdata": "{}", "is_deactivated": True},
}


@pytest.fixture(scope="module")
def app():
	app = Flask(__name__)
	app.secret_key = "test"

	# the only query these requests make is looking up the logged-in user
	app.db = MagicMock()
	app.db.fetchone.side_effect = lambda query, replacements=None: USERS.get(replacements[0]) if replacements else None

	# what the view module reads from the app while it is imported
	app.fourcat_config = types.SimpleNamespace(get=lambda setting, default=None: default)
	app.login_manager = LoginManager(app)
	app.limiter = Limiter(get_remote_address, app=app, storage_uri="memory://")
	app.autologin = types.SimpleNamespace(hostnames=[], api=[])

	webtool = types.ModuleType("webtool")
	webtool.__path__ = [str(Path(__file__).parent.parent.joinpath("webtool"))]
	loaded_before = set(sys.modules)
	with pytest.MonkeyPatch.context() as monkeypatch:
		monkeypatch.setitem(sys.modules, "webtool", webtool)
		with app.app_context():
			views_user = importlib.import_module("webtool.views.views_user")

	# do not leave modules that belong to the stand-in package behind
	for name in set(sys.modules) - loaded_before:
		if name.startswith("webtool."):
			del sys.modules[name]

	# stands in for every page outside the 'user' blueprint; the login view
	# redirects to this endpoint
	misc = Blueprint("misc", __name__)
	misc.add_url_rule("/", "show_frontpage", lambda: "front page")

	app.register_blueprint(views_user.component)
	app.register_blueprint(misc)
	return app


def logged_in_client(app, name):
	client = app.test_client()
	with client.session_transaction() as session:
		session["_user_id"] = name
		session["_fresh"] = True
	return client


def assert_logged_out_with_message(client, response):
	assert response.status_code == 302
	assert response.headers["Location"].endswith("/login/")
	with client.session_transaction() as session:
		assert "_user_id" not in session
		assert any("deactivated" in message for category, message in session.get("_flashes", []))


def test_deactivated_user_is_logged_out_on_any_page(app):
	client = logged_in_client(app, "deactivated@example.com")
	assert_logged_out_with_message(client, client.get("/"))


def test_deactivated_user_can_log_out(app):
	client = logged_in_client(app, "deactivated@example.com")
	assert_logged_out_with_message(client, client.get("/logout"))


def test_active_user_is_not_logged_out(app):
	client = logged_in_client(app, "active@example.com")
	response = client.get("/")
	assert response.status_code == 200
	with client.session_transaction() as session:
		assert session["_user_id"] == "active@example.com"
