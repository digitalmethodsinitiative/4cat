from unittest.mock import MagicMock

from backend.lib.proxied_requests import DelegatedRequestHandler
from common.lib.config_definition import config_definition


"""
The settings of 4CAT's shared request queue.

One request queue serves the whole backend: the web requests of every
processor wait in it, and it applies one set of proxy settings to all of them.
These settings therefore cannot differ per user tag, so they must be global.
"""


class RecordingConfig:
    """Settings reader that gives the default values and notes which settings were read"""
    def __init__(self):
        self.read = set()

    def get(self, name, default=None, **kwargs):
        self.read.add(name)
        return config_definition.get(name, {}).get("default", default)


def test_settings_of_the_shared_request_queue_are_global(monkeypatch):
    # the queue keeps its proxies in a class attribute; give this test its own
    monkeypatch.setattr(DelegatedRequestHandler, "proxy_pool", {})
    config = RecordingConfig()

    DelegatedRequestHandler(log=MagicMock(), config=config)

    assert "proxies.concurrent-overall" in config.read
    assert [name for name in config.read if not config_definition.get(name, {}).get("global")] == []
