"""
Tests for how the config manager uses memcache

Memcache only makes reading settings faster. When it cannot be used, settings
are read from the database instead, and nothing may fail because of it.
"""
import json

import pytest

from unittest.mock import MagicMock, patch
from pymemcache.exceptions import MemcacheUnexpectedCloseError

from common.config_manager import ConfigManager


class FakeMemcacheServer:
    """
    Values held by a memcache server that can be restarted or stopped
    """
    def __init__(self):
        self.values = {}
        self.expire = {}
        self.up = True
        self.started = 0
        self.connects = 0

    def restart(self):
        # a restart closes all connections and empties memcache
        self.values = {}
        self.started += 1


class FakeMemcacheClient:
    """
    Stands in for pymemcache's client

    Like pymemcache, it closes its connection after an error, and opens a new
    one on the next command.
    """
    def __init__(self, server):
        self.server = server
        self.sock = None

    def _run(self, command):
        if self.sock is None:
            self.server.connects += 1
            if not self.server.up:
                raise ConnectionRefusedError("Connection refused")
            self.sock = self.server.started

        if not self.server.up or self.sock != self.server.started:
            self.sock = None
            raise MemcacheUnexpectedCloseError()

        return command()

    def get(self, key, default=None):
        return self._run(lambda: self.server.values.get(key, default))

    def set(self, key, value, expire=0, noreply=None):
        def store():
            self.server.values[key] = value
            self.server.expire[key] = expire
            return True
        return self._run(store)

    def delete(self, key, noreply=None):
        return self._run(lambda: self.server.values.pop(key, None) is not None)

    def delete_many(self, keys, noreply=None):
        def remove():
            for key in keys:
                self.server.values.pop(key, None)
            return True
        return self._run(remove)

    def flush_all(self, noreply=None):
        return self._run(lambda: self.server.values.clear())


class FakeDatabase:
    """
    Stands in for the settings table
    """
    def __init__(self):
        self.settings = {}
        self.cursor = MagicMock(rowcount=1)
        self.log = MagicMock()

    def fetchall(self, query, replacements):
        name, tags = replacements
        return [{"tag": tag, "value": value} for (setting, tag), value in self.settings.items()
                if setting == name and tag in tags]

    def execute(self, query, replacements):
        name, value, tag = replacements
        self.settings[(name, tag)] = value


@pytest.fixture
def server():
    return FakeMemcacheServer()


@pytest.fixture
def config(server):
    """
    A config manager with a fake database and a fake memcache server
    """
    instance = object.__new__(ConfigManager)
    instance.core_settings = {"MEMCACHE_SERVER": "memcached:11211"}
    instance.config_definition = {}
    instance.db = FakeDatabase()
    instance.logger = MagicMock()

    ConfigManager._memcache_down = False
    ConfigManager._memcache_tls.__dict__.clear()

    with patch("common.config_manager.MemcacheClient", lambda *args, **kwargs: FakeMemcacheClient(server)):
        yield instance

    ConfigManager._memcache_down = False
    ConfigManager._memcache_tls.__dict__.clear()


def test_values_are_cached_with_an_expiry_time(config, server):
    config.set("4cat.name", "Test 4CAT")

    assert config.get("4cat.name") == "Test 4CAT"
    key = config._get_memcache_id("4cat.name", "")
    assert server.values[key] == json.dumps("Test 4CAT")
    assert server.expire[key] == ConfigManager.memcache_expire


def test_restart_is_not_noticed(config, server):
    config.set("4cat.name", "Test 4CAT")
    config.get("4cat.name")

    server.restart()

    assert config.get("4cat.name") == "Test 4CAT"
    assert not ConfigManager._memcache_down
    config.logger.warning.assert_not_called()
    # cached again after the restart
    assert config._get_memcache_id("4cat.name", "") in server.values


def test_changed_setting_is_removed_after_restart(config, server):
    config.set("4cat.name", "Old name")
    config.get("4cat.name")

    server.restart()
    config.set("4cat.name", "New name")

    assert not ConfigManager._memcache_down
    assert config.get("4cat.name") == "New name"


def test_outage_reads_from_database_until_restart(config, server):
    config.set("4cat.name", "Test 4CAT")
    config.get("4cat.name")

    server.up = False
    assert config.get("4cat.name") == "Test 4CAT"
    assert ConfigManager._memcache_down
    assert config.logger.warning.call_count == 1

    # memcache is not tried again, not even once it works again
    connects = server.connects
    server.up = True
    assert config.get("4cat.name") == "Test 4CAT"
    assert server.connects == connects
    assert config.logger.warning.call_count == 1


def test_unreachable_from_the_start(config, server):
    server.up = False

    assert config.get("4cat.name", default="fallback") == "fallback"
    assert ConfigManager._memcache_down
    assert config.logger.warning.call_count == 1


def test_change_while_down_leaves_old_value_cached(config, server):
    """
    A setting changed while this process cannot reach memcache stays cached
    with its old value, for processes that can still reach it, until the
    value expires
    """
    config.set("4cat.name", "Old name")
    config.get("4cat.name")
    key = config._get_memcache_id("4cat.name", "")

    server.up = False
    config.set("4cat.name", "New name")
    server.up = True

    assert config.get("4cat.name") == "New name"
    assert server.values[key] == json.dumps("Old name")
    assert server.expire[key] == ConfigManager.memcache_expire


def test_cache_clear_does_not_fail_while_down(config, server):
    server.up = False
    config.clear_cache()
    config.uncache_user_tags(["someone@example.com"])


def test_without_memcache_nothing_is_cached(config, server):
    config.core_settings = {"MEMCACHE_SERVER": None}
    config.set("4cat.name", "Test 4CAT")

    assert config.get("4cat.name") == "Test 4CAT"
    assert server.connects == 0


@pytest.mark.parametrize("name", ["jürgen@example.com", "first last@example.com", "x" * 300 + "@example.com"])
def test_unusual_user_names_make_valid_keys(name):
    key = ConfigManager._memcache_key(f"_usertags-{name}")

    assert key.startswith("hash-")
    assert key.isascii() and key.isprintable() and " " not in key and len(key) <= 200


def test_ordinary_keys_are_kept():
    assert ConfigManager._memcache_key("4cat.name-user:someone@example.com") == "4cat.name-user:someone@example.com"
