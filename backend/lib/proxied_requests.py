from requests_futures.sessions import FuturesSession
from concurrent.futures import ThreadPoolExecutor

import time
import urllib3
import ural
import requests
from collections import namedtuple

from common.config_manager import config


class FailedRequest:
    """
    A delegated request that has failed for whatever reason

    The failure context (usually the exception) is stored in the `context`
    property.
    """

    def __init__(self, context=None):
        self.context = context


class ProxyStatus:
    """
    An enum of possible statuses of a SophisticatedFuturesProxy
    """

    AVAILABLE = 3
    CLAIMED = 4
    RUNNING = 5
    COOLING_OFF = 6


class SophisticatedFuturesProxy:
    """
    A proxy that can be used in combination with the DelegatedRequestHandler

    This keeps track of cooloffs, etc, to ensure that any individual proxy does
    not request more often than it should. This is a separate class because of
    an additional piece of logic that allows this cooloff to be kept track of
    on a per-hostname basis. This is useful because rate limits are typically
    enforced per site, so we can have (figuratively) unlimited concurrent
    request as long as each is on a separate hostname, but need to be more
    careful when requesting from a single host.
    """

    log = None

    COOLOFF = 0
    MAX_CONCURRENT_OVERALL = 0
    MAX_CONCURRENT_PER_HOST = 0

    def __init__(
        self, url, log=None, cooloff=3, concurrent_overall=5, concurrent_host=2
    ):
        self.proxy_url = url
        self.hostnames = {}
        self.log = log

        self.COOLOFF = cooloff
        self.MAX_CONCURRENT_OVERALL = concurrent_overall
        self.MAX_CONCURRENT_PER_HOST = concurrent_host

    def know_hostname(self, hostname):
        """
        Make sure the hostname is known to this proxy

        This means that we can now keep track of some per-hostname statistics
        for this hostname. If the hostname is not known yet, the statistics are
        re-initialised.

        :param str hostname:  Host name to keep stats for. Case-insensitive.
        """
        hostname = hostname.lower()
        if hostname not in self.hostnames:
            self.hostnames[hostname] = namedtuple(
                "HostnameForProxiedRequests", ("last_request_start", "running")
            )
            self.hostnames[hostname].last_request_start = 0
            self.hostnames[hostname].running = []

    def release_cooled_off(self):
        """
        Release proxies that have finished cooling off.

        Proxies cool off for a certain amount of time after starting a request.
        This method removes cooled off requests, so that new ones may fill
        their slot.
        """
        for hostname, metadata in self.hostnames.items():
            for i, request in enumerate(metadata.running):
                if (
                    request.status == ProxyStatus.COOLING_OFF
                    and request.timestamp_started < time.time() - self.COOLOFF
                ):
                    self.log.debug(
                        f"Releasing proxy {self.proxy_url} for host name {hostname}"
                    )
                    del self.hostnames[hostname].running[i]

    def claim_for(self, url):
        """
        Try claiming a slot in this proxy for the given URL

        Whether a slot is available depends both on the overall concurrency
        limit, and the per-hostname limit. If both are not maxed out, fill
        the slot and return the proxy object.

        :param str url:  URL to proxy a request for.
        :return: `False` if no proxy is available, or the
        `SophisticatedFuturesProxy` object if one is.
        """
        self.release_cooled_off()
        hostname = ural.get_hostname(url)
        self.know_hostname(hostname)

        total_running = sum([len(m.running) for h, m in self.hostnames.items()])
        if total_running >= self.MAX_CONCURRENT_OVERALL:
            return False

        if len(self.hostnames[hostname].running) < self.MAX_CONCURRENT_PER_HOST:
            request = namedtuple(
                "ProxiedRequest", ("url", "status", "timestamp_started")
            )
            request.url = url
            request.status = ProxyStatus.CLAIMED
            request.timestamp_started = 0
            self.hostnames[hostname].running.append(request)
            self.log.debug(
                f"Claiming proxy {self.proxy_url} for host name {hostname} ({len(self.hostnames[hostname].running)} of {self.MAX_CONCURRENT_PER_HOST} for host)"
            )
            return self
        else:
            return False

    def request_started(self, url):
        """
        Mark a request for a URL as started

        This updates the status for the related slot. If no matching slot
        exists that is waiting for a request to start running, a `ValueError`
        is raised.

        :param str url:  URL of the proxied request.
        """
        hostname = ural.get_hostname(url)
        self.know_hostname(hostname)

        self.hostnames[hostname].last_request_start = time.time()
        for i, metadata in enumerate(self.hostnames[hostname].running):
            if metadata.status == ProxyStatus.CLAIMED and metadata.url == url:
                self.hostnames[hostname].running[i].status = ProxyStatus.RUNNING
                self.hostnames[hostname].running[i].timestamp_started = time.time()
                return

        raise ValueError(f"No proxy is waiting for a request with URL {url} to start!")

    def request_finished(self, url):
        """
        Mark a request for a URL as finished

        This updates the status for the related slot. If no matching slot
        exists that is waiting for a request to finish, a `ValueError` is
        raised. After this, the proxy will be marked as cooling off, and is
        released after cooling off is completed.

        :param str url:  URL of the proxied request.
        """
        hostname = ural.get_hostname(url)
        self.know_hostname(hostname)

        for i, metadata in enumerate(self.hostnames[hostname].running):
            if metadata.status == ProxyStatus.RUNNING and metadata.url == url:
                self.hostnames[hostname].running[i].status = ProxyStatus.COOLING_OFF
                return

        raise ValueError(f"No proxy is currently running a request for URL {url}!")


class DelegatedRequestHandler:
    queue = {}
    requests = {}
    session = None
    proxy_pool = {}
    log = None

    # some magic values
    REQUEST_STATUS_STARTED = 1
    REQUEST_STATUS_WAITING_FOR_YIELD = 2
    PROXY_LOCALHOST = "__localhost__"

    def __init__(self, log):
        pool = ThreadPoolExecutor()
        self.session = FuturesSession(executor=pool)
        self.log = log

    def add_urls(self, urls, queue_name="_"):
        if queue_name not in self.queue:
            self.queue[queue_name] = []
            self.requests[queue_name] = []

        self.queue[queue_name].extend(urls)
        self.manage_requests()

    def get_queue_length(self, queue_name="_"):
        if queue_name not in self.queue:
            self.queue[queue_name] = []
            self.requests[queue_name] = []

        return len(self.queue[queue_name])

    def claim_proxy(self, url):
        """
        Find a proxy to do the request with

        Finds a `SophisticatedFuturesProxy` that has an open slot for this URL.

        :param str url:  URL to proxy a request for
        :return SophisticatedFuturesProxy or False:
        """
        if not self.proxy_pool:
            # this will trigger the first time this method is called
            # build a proxy pool with some information per available proxy
            proxies = config.get("proxies.urls")
            for proxy_url in proxies:
                self.proxy_pool[proxy_url] = namedtuple(
                    "ProxyEntry", ("proxy", "last_used")
                )
                self.proxy_pool[proxy_url].proxy = SophisticatedFuturesProxy(
                    proxy_url,
                    self.log,
                    config.get("proxies.cooloff"),
                    config.get("proxies.concurrent-overall"),
                    config.get("proxies.concurrent-host"),
                )
                self.proxy_pool[proxy_url].last_used = 0

            self.log.debug(f"Proxy pool has {len(self.proxy_pool)} available proxies.")

        # within the pool, find the least recently used proxy that is available
        sorted_by_cooloff = sorted(
            self.proxy_pool, key=lambda p: self.proxy_pool[p].last_used
        )
        for proxy_id in sorted_by_cooloff:
            claimed_proxy = self.proxy_pool[proxy_id].proxy.claim_for(url)
            if claimed_proxy:
                self.proxy_pool[proxy_id].last_used = time.time()
                return claimed_proxy

        return False

    def manage_requests(self):
        """
        Manage requests asynchronously

        First, make sure proxy status is up to date; then go through the list
        of queued URLs and see if they have been requested, and release the
        proxy accordingly. If the URL is not being requested, and a proxy is
        available, start the request.

        Note that this method does *not* return any requested data. This is
        done in a separate function, which calls this one before returning any
        finished requests in the original queue order (`get_results()`).
        """
        # go through queue and look at the status of each URL
        for queue_name in self.queue:
            for url in self.queue[queue_name]:
                # is there a request for the url?
                have_request = False
                for request in self.requests[queue_name]:
                    if (
                        request.url != url
                        or request.status == self.REQUEST_STATUS_WAITING_FOR_YIELD
                    ):
                        # look for the first request with this URL that is not
                        # done yet and then break (see below) - this means we
                        # can handle multiple requests for the same URL
                        have_request = request.url == url
                        continue

                    have_request = True
                    # is the request done?
                    if request.request.done():
                        # collect result and buffer it for yielding (see below for
                        # why we do not immediately yield)
                        self.log.debug(f"Request for {url} finished, collecting result")
                        request.proxy.request_finished(url)
                        try:
                            response = request.request.result()
                            request.result = response
                        except (
                            ConnectionError,
                            requests.exceptions.RequestException,
                            urllib3.exceptions.HTTPError,
                        ) as e:
                            request.result = FailedRequest(e)
                        finally:
                            request.status = self.REQUEST_STATUS_WAITING_FOR_YIELD
                    else:
                        # running - ignore for now
                        # potentially check for timeouts, etc
                        # logging.debug(f"Request for {url} running...")
                        pass

                    break

                if not have_request:
                    proxy = self.claim_proxy(url)
                    if not proxy:
                        # no available proxies, try again next loop
                        continue

                    proxy_url = proxy.proxy_url
                    proxy_definition = (
                        {"http": proxy_url, "https": proxy_url}
                        if proxy_url != self.PROXY_LOCALHOST
                        else None
                    )

                    # start request for URL
                    self.log.debug(f"Request for {url} started")
                    request = namedtuple(
                        "DelegatedRequest",
                        ("request", "created", "status", "result", "proxy", "url"),
                    )
                    request.created = time.time()
                    request.request = self.session.get(
                        url, timeout=30, proxies=proxy_definition
                    )
                    request.status = self.REQUEST_STATUS_STARTED
                    request.proxy = proxy
                    request.url = url

                    self.requests[queue_name].append(request)
                    proxy.request_started(url)

    def get_results(self, queue_name="_"):
        """
        Return available results, without skipping

        Loops through the queue, returning values (and updating the queue) for
        requests that have been finished. If a request is not finished yet,
        stop returning. This ensures that in the end, values are only ever
        returned in the original queue order, at the cost of potential
        buffering.

        :return:
        """
        self.manage_requests()
        for url in self.queue[queue_name]:
            for i, request in enumerate(self.requests[queue_name]):
                if (
                    request.url == url
                    and request.status == self.REQUEST_STATUS_WAITING_FOR_YIELD
                ):
                    yield url, request.result
                    del self.requests[queue_name][i]
                    self.queue[queue_name].pop(0)
                else:
                    break
