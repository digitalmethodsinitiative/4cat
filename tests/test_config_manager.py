"""
Two ConfigManager behaviours that are load-bearing and easy to regress unnoticed.

  1. `get()` falls back to the definition's default only when no row exists; a
     stored value always wins. This is why removing a row is not the same as
     removing a setting, and why a definition's default is reachable at all -
     which is what makes a module overriding a core definition dangerous.

  2. `ensure_database()` creates settings that are missing from the database, but
     never removes ones it does not recognise. A setting can be undeclared
     because its extension is uninstalled or disabled, or because its module
     failed to import this boot, so absence from the config definition says
     nothing about whether the stored value is still wanted.
"""
import pytest

from unittest.mock import MagicMock, patch


@pytest.fixture
def config():
    """
    A ConfigManager wired to a mock database, without reading config.ini

    Built with `object.__new__` so no config/config.ini is required. Note that
    `core_settings` and `config_definition` are *class* attributes; assigning
    them here creates instance attributes that shadow the class ones, so tests
    cannot leak definitions into each other.
    """
    with patch("common.config_manager.Database"):
        from common.config_manager import ConfigManager

        manager = object.__new__(ConfigManager)
        manager.core_settings = {}
        manager.config_definition = {}
        manager.db = MagicMock()
        manager.db.log = MagicMock()
        manager.logger = None
        manager.get_memcache = MagicMock(return_value=None)

        yield manager


def test_stored_value_wins_over_definition_default(config):
    """
    The default applies only when nothing is stored, and never overrides a value
    that is.
    """
    config.config_definition = {"test.setting": {"default": "the-default"}}

    config.db.fetchall.return_value = []
    assert config.get("test.setting") == "the-default"

    config.db.fetchall.return_value = [{"tag": "", "value": '"the-stored-value"'}]
    assert config.get("test.setting") == "the-stored-value"


def test_ensure_database_does_not_delete_undeclared_settings(config):
    """
    The database here holds `orphan.setting`, which no definition declares. It
    must survive: no delete() call, and no DELETE issued directly.
    """
    def fetchall(query, *args, **kwargs):
        if "FROM users" in query:
            return [{"tags": []}]
        if "DISTINCT tag FROM settings" in query:
            return [{"tag": ""}]
        if "DISTINCT name FROM settings" in query:
            return [{"name": "orphan.setting"}, {"name": "flask.tag_order"}]
        return []

    config.db.fetchall.side_effect = fetchall
    config.config_definition = {"flask.tag_order": {"default": ["admin"]}}

    config.ensure_database()

    config.db.delete.assert_not_called()
    executed = " ".join(str(call) for call in config.db.execute.call_args_list)
    assert "DELETE" not in executed.upper(), f"ensure_database() issued a DELETE: {executed}"
