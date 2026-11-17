"""
Tests for whether a newly created dataset is private

A dataset is private, unless the user creating it may make datasets public and
has asked for that. These tests run the real view that creates datasets.

Importing the `webtool` package would start the whole web tool, so an empty
stand-in package takes its place while the view module is loaded.
"""
import importlib
import inspect
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from flask import Flask, g
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

ROOT = Path(__file__).parent.parent
PERMISSION = "privileges.can_make_dataset_public"


class Worker:
    """
    The least a data source worker needs in order to create a dataset
    """
    type = "test-search"
    extension = "csv"

    @staticmethod
    def get_options(parent_dataset=None, config=None):
        return {}

    @staticmethod
    def validate_query(query, request, config):
        return query


@pytest.fixture(scope="module")
def api_tool():
    app = Flask(__name__)
    app.limiter = Limiter(get_remote_address, app=app, storage_uri="memory://")
    app.openapi = MagicMock()
    app.openapi.endpoint.return_value = lambda view: view

    webtool = types.ModuleType("webtool")
    webtool.__path__ = [str(ROOT.joinpath("webtool"))]
    loaded_before = set(sys.modules)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setitem(sys.modules, "webtool", webtool)
        with app.app_context():
            module = importlib.import_module("webtool.views.api_tool")

    # do not leave modules that belong to the stand-in package behind
    for name in set(sys.modules) - loaded_before:
        if name.startswith("webtool."):
            del sys.modules[name]

    return module


def create_dataset(api_tool, monkeypatch, may_make_public, form):
    """
    Create a dataset through the real view

    :return bool:  Whether the dataset was created as a private one
    """
    dataset_class = MagicMock()
    dataset_class.return_value.key = "abc"
    monkeypatch.setattr(api_tool, "DataSet", dataset_class)
    monkeypatch.setattr(api_tool, "Job", MagicMock())
    monkeypatch.setattr(api_tool, "current_user", MagicMock())
    monkeypatch.setattr(api_tool, "url_for", lambda *args, **kwargs: "", raising=False)

    app = Flask(__name__)
    with app.test_request_context("/api/queue-query/", method="POST",
                                  data={"datasource": "test", "frontend-confirm": "true", **form}):
        g.config = MagicMock()
        g.config.get.side_effect = lambda key, default=None: may_make_public if key == PERMISSION else default
        g.db = MagicMock()
        g.queue = MagicMock()
        g.modules = MagicMock()
        g.modules.datasources = {"test": {"name": "Test"}}
        g.modules.workers = {"test-search": Worker}
        g.modules.get_datasource_worker.return_value = Worker
        inspect.unwrap(api_tool.queue_dataset)()

    return dataset_class.call_args.kwargs["is_private"]


@pytest.mark.parametrize("may_make_public, form, private", [
    pytest.param(False, {}, True, id="no permission, did not ask"),
    pytest.param(True, {}, True, id="permission, box left unticked"),
    pytest.param(True, {"make-public": "on"}, False, id="permission, box ticked"),
    pytest.param(False, {"make-public": "on"}, True, id="no permission, asked anyway"),
    pytest.param(True, {"make-public": ""}, True, id="permission, empty answer"),
    pytest.param(True, {"make-private": ""}, True, id="permission, old field does not count"),
])
def test_dataset_is_private_unless_allowed_and_asked(api_tool, monkeypatch, may_make_public, form, private):
    assert create_dataset(api_tool, monkeypatch, may_make_public, form) is private
