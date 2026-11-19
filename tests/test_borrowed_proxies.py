from unittest.mock import MagicMock

import pytest

from backend.lib.proxied_requests import DelegatedRequestHandler, NoProxiesAvailableError
from common.lib.exceptions import ProcessorInterruptedException


"""
Borrowing a proxy from 4CAT's shared proxies.

Tools that make their own requests, such as yt-dlp, cannot go through the
queue of proxied requests. They borrow one proxy instead, for as long as they
need it. A borrowed proxy counts as running one request for one host, so the
same limits apply as for queued requests, and the other proxies and hosts stay
free for other processors.
"""

FIRST = "http://user:secret@10.0.0.1:3128"
SECOND = "http://user:secret@10.0.0.2:3128"
SOCKS = "socks5://user:secret@10.0.0.3:1080"
TIKTOK_POST = "https://www.tiktok.com/@user/video/1"
OTHER_TIKTOK_POST = "https://www.tiktok.com/@user/video/2"
OTHER_WEBSITE = "https://www.example.com/image.jpg"


class Settings:
    """Proxy settings, as 4CAT's settings reader gives them"""
    def __init__(self, urls, fallback=True):
        self.values = {
            "proxies.urls": urls,
            "proxies.cooloff": 0,
            "proxies.concurrent-overall": 4,
            "proxies.concurrent-host": 1,
            "proxies.allow-localhost-fallback": fallback,
            "proxies.healthcheck-url": "http://healthcheck.invalid/",
        }

    def get(self, name, default=None, **kwargs):
        return self.values.get(name, default)


@pytest.fixture
def make_pool(monkeypatch):
    """Make a pool of proxies with the given proxy URLs, apart from 4CAT's own"""
    def make(urls, fallback=True):
        # the pool keeps its proxies and queues in class attributes
        monkeypatch.setattr(DelegatedRequestHandler, "proxy_pool", {})
        monkeypatch.setattr(DelegatedRequestHandler, "queue", {})
        return DelegatedRequestHandler(log=MagicMock(), config=Settings(urls, fallback))

    return make


def has_room(pool, proxy_url, url):
    """Whether the proxy could take a request for this URL now (this takes the place)"""
    return bool(pool.proxy_pool[proxy_url].proxy.claim_for(url))


def test_a_borrowed_proxy_is_busy_for_that_website_only(make_pool):
    pool = make_pool([FIRST, SECOND])

    with pool.borrow_proxy(TIKTOK_POST) as proxy_url:
        assert proxy_url == FIRST
        assert not has_room(pool, FIRST, OTHER_TIKTOK_POST)
        assert has_room(pool, FIRST, OTHER_WEBSITE)
        assert has_room(pool, SECOND, OTHER_TIKTOK_POST)


def test_a_second_borrower_gets_the_other_proxy(make_pool):
    pool = make_pool([FIRST, SECOND])

    with pool.borrow_proxy(TIKTOK_POST) as first:
        with pool.borrow_proxy(OTHER_TIKTOK_POST) as second:
            assert {first, second} == {FIRST, SECOND}


def test_the_proxy_is_given_back_when_the_download_fails(make_pool):
    pool = make_pool([FIRST])

    with pytest.raises(RuntimeError):
        with pool.borrow_proxy(TIKTOK_POST):
            raise RuntimeError("the download failed")

    assert not pool.proxy_pool[FIRST].proxy.has_active_requests()


def test_borrowing_waits_for_a_busy_proxy(make_pool):
    pool = make_pool([FIRST])
    first_borrower = pool.borrow_proxy(TIKTOK_POST)
    first_borrower.__enter__()
    waited = []

    def give_back_while_waiting():
        waited.append(True)
        first_borrower.__exit__(None, None, None)

    with pool.borrow_proxy(OTHER_TIKTOK_POST, on_wait=give_back_while_waiting, wait=0.01) as proxy_url:
        assert proxy_url == FIRST

    assert waited


def test_an_interrupted_processor_stops_waiting(make_pool):
    pool = make_pool([FIRST])

    def interrupted():
        raise ProcessorInterruptedException("Interrupted while downloading videos.")

    with pool.borrow_proxy(TIKTOK_POST):
        with pytest.raises(ProcessorInterruptedException):
            with pool.borrow_proxy(OTHER_TIKTOK_POST, on_wait=interrupted):
                pass


def test_unhealthy_proxies_are_not_lent(make_pool):
    pool = make_pool([FIRST, SECOND])
    pool.proxy_health[FIRST] = False

    with pool.borrow_proxy(TIKTOK_POST) as proxy_url:
        assert proxy_url == SECOND


def test_only_proxies_of_the_asked_kind_are_lent(make_pool):
    # ffmpeg ignores SOCKS proxies, so yt-dlp only borrows http:// ones
    pool = make_pool([SOCKS, FIRST])

    with pool.borrow_proxy(TIKTOK_POST, only_schemes=("http://",)) as proxy_url:
        assert proxy_url == FIRST


def test_without_a_proxy_of_that_kind_the_connection_is_direct(make_pool):
    pool = make_pool([SOCKS])

    with pool.borrow_proxy(TIKTOK_POST, only_schemes=("http://",)) as proxy_url:
        assert proxy_url == DelegatedRequestHandler.PROXY_LOCALHOST

    # queued requests of other processors keep using the SOCKS proxy only
    assert list(pool.proxy_pool) == [SOCKS]


def test_without_a_proxy_of_that_kind_and_no_fallback_nothing_is_lent(make_pool):
    pool = make_pool([SOCKS], fallback=False)

    with pytest.raises(NoProxiesAvailableError, match="http://"):
        with pool.borrow_proxy(TIKTOK_POST, only_schemes=("http://",)):
            pass


def test_a_direct_connection_in_the_list_counts_like_a_proxy(make_pool):
    # the default setting: no proxies, but still one request per website at a time
    pool = make_pool([DelegatedRequestHandler.PROXY_LOCALHOST])

    with pool.borrow_proxy(TIKTOK_POST, only_schemes=("http://",)) as proxy_url:
        assert proxy_url == DelegatedRequestHandler.PROXY_LOCALHOST
        assert not has_room(pool, DelegatedRequestHandler.PROXY_LOCALHOST, OTHER_TIKTOK_POST)


def test_a_proxy_taken_out_of_the_settings_goes_once_it_is_given_back(make_pool):
    pool = make_pool([FIRST])

    with pool.borrow_proxy(TIKTOK_POST):
        pool.refresh_settings(Settings([SECOND]))
        assert FIRST in pool.proxy_pool

    assert FIRST not in pool.proxy_pool
