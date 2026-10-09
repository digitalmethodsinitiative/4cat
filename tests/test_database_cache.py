"""
Tests for the cache in front of the database

Memcache only makes reading faster. When it is restarted (e.g. by a system
update) or cannot be reached, data should be read from the database instead of
requests failing. And because all of 4CAT's processes read the same cache,
memcache must be cleared before it is used again after a failure: data whose
cached value could not be removed when it changed would otherwise be read
again.
"""
import json
import socket
import threading
import time

import pytest

from unittest.mock import MagicMock
from pymemcache.client.base import check_key_helper
from pymemcache.exceptions import MemcacheServerError, MemcacheUnexpectedCloseError, MemcacheUnknownCommandError

import common.lib.database_cache
from common.lib.database_cache import DatabaseCache, CacheMiss
from common.config_manager import ConfigManager


class FakeMemcacheServer:
    """
    Stand-in for a memcache server, shared by the clients connected to it
    """
    def __init__(self):
        self.values = {}
        self.expire = {}
        self.reachable = True
        self.timeouts = 0
        self.restarts = 0
        self.commands = 0
        self.refuse_values = False
        self.refuse_removals = False
        self.refuse_clearing = False

    def restart(self):
        """
        Forget all values and close the connections that are open
        """
        self.values.clear()
        self.restarts += 1


class FakeMemcacheClient:
    """
    Stand-in for a pymemcache client
    """
    def __init__(self, server):
        self.server = server
        self.connected_after_restarts = server.restarts

    def _check(self):
        self.server.commands += 1
        if not self.server.reachable:
            raise ConnectionRefusedError()
        if self.server.timeouts:
            self.server.timeouts -= 1
            raise socket.timeout()
        if self.connected_after_restarts != self.server.restarts:
            raise MemcacheUnexpectedCloseError()

    def version(self):
        self._check()
        return b"1.6"

    def get(self, key, default=None):
        check_key_helper(key, False, b"test")
        self._check()
        return self.server.values.get(key, default)

    def set(self, key, value, expire=0, noreply=None):
        check_key_helper(key, False, b"test")
        self._check()
        if self.server.refuse_values:
            raise MemcacheServerError("object too large for cache")
        self.server.values[key] = value
        self.server.expire[key] = expire
        return True

    def delete(self, key, noreply=None):
        check_key_helper(key, False, b"test")
        self._check()
        if self.server.refuse_removals:
            raise MemcacheServerError("out of memory")
        self.server.values.pop(key, None)
        return True

    def flush_all(self, noreply=None):
        self._check()
        if self.server.refuse_clearing:
            raise MemcacheUnknownCommandError()
        self.server.values.clear()
        return True

    def close(self):
        pass


@pytest.fixture
def server(monkeypatch):
    server = FakeMemcacheServer()
    monkeypatch.setattr(common.lib.database_cache, "MemcacheClient", lambda *args, **kwargs: FakeMemcacheClient(server))
    return server


@pytest.fixture
def cache(server):
    return DatabaseCache("localhost:11211", key_prefix=b"test", logger=MagicMock())


def time_for_next_attempt(cache):
    cache._next_attempt = 0


def make_config_manager(memcache_server):
    """
    Config manager built without running __init__, which would read
    config.ini and connect to the database
    """
    instance = object.__new__(ConfigManager)
    instance.core_settings = {"MEMCACHE_SERVER": memcache_server}
    instance.db = MagicMock()
    instance.logger = MagicMock()
    return instance


def test_values_are_cached_and_expire(cache, server):
    cache.set("key", "value")

    assert cache.get("key") == "value"
    assert server.expire[b"key"] == DatabaseCache.expire
    assert cache.get("other key") is CacheMiss


def test_any_key_can_be_cached(cache, server):
    """
    Keys are made from setting names, tags and user names, which can contain
    characters memcache does not accept in a key. Their values are cached all
    the same.
    """
    keys = ["user:müller@example.com", "tag with spaces", "x" * 300]
    for key in keys:
        cache.set(key, key)

    assert [cache.get(key) for key in keys] == keys
    cache.logger.warning.assert_not_called()

    cache.delete(keys[0])
    assert cache.get(keys[0]) is CacheMiss
    assert cache._down_since is None


def test_restart_handled_by_reconnecting(cache, server):
    """
    A restart closes the connection that is open. Trying again with a new
    connection works, so memcache is not considered down and there is no
    warning.
    """
    cache.set("key", "value")
    server.restart()

    assert cache.get("key") is CacheMiss
    assert cache._down_since is None
    cache.logger.warning.assert_not_called()
    assert "probably restarted" in cache.logger.info.call_args.args[0]


def test_unreachable_memcache(cache, server):
    """
    While memcache is down, nothing is read from it, and it is not tried for
    each value
    """
    server.reachable = False
    assert cache.get("key") is CacheMiss
    assert cache._down_since is not None

    commands = server.commands
    assert cache.get("key") is CacheMiss
    assert not cache.is_available()
    assert server.commands == commands

    cache.logger.warning.assert_called_once()


def test_cleared_before_use_after_failed_removal(cache, server):
    """
    If a cached value cannot be removed, it is not read: memcache is not used
    until it has been cleared
    """
    cache.set("key", "old value")

    # the removal and the retry time out, while memcache keeps its values
    server.timeouts = 2
    cache.delete("key")
    assert server.values[b"key"] == "old value"
    assert cache.get("key") is CacheMiss

    time_for_next_attempt(cache)
    assert cache.get("key") is CacheMiss
    assert cache._down_since is None
    assert "can be reached again" in cache.logger.info.call_args.args[0]


def test_refused_value_does_not_stop_memcache(cache, server):
    """
    Memcache refusing a value (e.g. one too large to store) does not mean it
    is down: that value is not cached, and memcache is still used
    """
    server.refuse_values = True
    cache.set("key", "value")
    assert cache._down_since is None
    assert "refused" in cache.logger.warning.call_args.args[0]

    server.refuse_values = False
    cache.set("key", "value")
    assert cache.get("key") == "value"


def test_refused_removal_counts_as_failure(cache, server):
    """
    When memcache answers a removal with an error, the old value may still be
    cached, so memcache is not used until it has been cleared
    """
    cache.set("key", "old value")

    server.refuse_removals = True
    cache.delete("key")
    assert cache._down_since is not None
    assert cache.get("key") is CacheMiss


def test_clearing_answered_with_error_counts_as_failure(cache, server):
    """
    When memcache answers a clearing with an error (e.g. a memcache proxy that
    does not support it), old values may still be cached, so memcache is not
    used until it has been cleared
    """
    server.refuse_clearing = True
    cache.clear()
    assert cache._down_since is not None


def test_system_error_when_connecting(cache, monkeypatch):
    """
    A SystemError while connecting is handled like other connection problems:
    data is read from the database instead
    """
    def broken_client(*args, **kwargs):
        raise SystemError()

    monkeypatch.setattr(common.lib.database_cache, "MemcacheClient", broken_client)

    assert cache.get("key") is CacheMiss
    assert cache._down_since is not None


def test_one_attempt_at_a_time(cache, server, monkeypatch):
    """
    While one thread tries to reach memcache again, the others do not also try
    """
    server.reachable = False
    cache.get("key")
    server.reachable = True
    time_for_next_attempt(cache)

    other_thread_ready = []
    original_flush_all = FakeMemcacheClient.flush_all

    def flush_all(client, noreply=None):
        other_thread = threading.Thread(target=lambda: other_thread_ready.append(cache._ready()))
        other_thread.start()
        other_thread.join()
        return original_flush_all(client, noreply)

    monkeypatch.setattr(FakeMemcacheClient, "flush_all", flush_all)

    assert cache._ready()
    assert other_thread_ready == [False]


def test_error_while_clearing_keeps_memcache_down(cache, server, monkeypatch):
    """
    If another thread runs into an error while memcache is being cleared, the
    clearing may have come too early to cover it, so memcache stays down and
    is cleared again on the next attempt
    """
    server.reachable = False
    cache.get("key")
    server.reachable = True
    time_for_next_attempt(cache)

    original_flush_all = FakeMemcacheClient.flush_all

    def flush_all(client, noreply=None):
        result = original_flush_all(client, noreply)
        cache._failed(ConnectionResetError())
        return result

    monkeypatch.setattr(FakeMemcacheClient, "flush_all", flush_all)

    assert not cache._ready()
    assert cache._down_since is not None


def test_clock_change_does_not_keep_memcache_down(cache, server, monkeypatch):
    """
    Changing the computer's clock (e.g. when it is synchronised) does not
    change when memcache is tried again
    """
    server.reachable = False
    cache.get("key")
    server.reachable = True
    time_for_next_attempt(cache)

    an_hour_ago = time.time() - 3600
    monkeypatch.setattr(time, "time", lambda: an_hour_ago)

    assert cache._ready()


def test_reminder_while_still_down(cache, server):
    server.reachable = False
    cache.get("key")
    cache.logger.warning.assert_called_once()

    # an attempt soon after: no new warning
    time_for_next_attempt(cache)
    cache.get("key")
    cache.logger.warning.assert_called_once()

    # an attempt after the reminder interval: reminder
    time_for_next_attempt(cache)
    cache._reminded_at -= DatabaseCache.reminder_interval
    cache.get("key")
    assert cache.logger.warning.call_count == 2
    assert "still cannot be reached" in cache.logger.warning.call_args.args[0]


def test_config_manager_reads_changed_setting_after_failed_removal(server, monkeypatch):
    """
    All config managers share one cache, and a setting that changed is read
    correctly even if its cached value could not be removed
    """
    monkeypatch.setattr(ConfigManager, "_cache", None)

    config = make_config_manager("localhost:11211")
    assert config.cache is make_config_manager("localhost:11211").cache

    config.db.fetchall.return_value = [{"tag": "", "value": json.dumps("old value")}]
    assert config.get("test.setting") == "old value"

    server.timeouts = 2
    config.db.fetchall.return_value = [{"tag": "", "value": json.dumps("new value")}]
    config.set("test.setting", "new value")
    assert config.get("test.setting") == "new value"

    time_for_next_attempt(config.cache)
    assert config.get("test.setting") == "new value"


@pytest.mark.parametrize("memcache_server", ["localhost:11211", None])
def test_config_manager_reads_setting_for_any_user_name(server, monkeypatch, memcache_server):
    """
    A user name with characters memcache does not accept in a key does not
    stop settings from being read, with or without memcache
    """
    monkeypatch.setattr(ConfigManager, "_cache", None)

    config = make_config_manager(memcache_server)
    config.db.fetchone.return_value = {"tags": []}
    config.db.fetchall.return_value = [{"tag": "", "value": json.dumps("value")}]

    assert config.get("test.setting", user="müller@example.com") == "value"
    config.logger.warning.assert_not_called()
