from requests_futures.sessions import FuturesSession
from concurrent.futures import ThreadPoolExecutor

import time
import urllib3
import ural
import requests

from collections import namedtuple
from asyncio import CancelledError as asyncioCancelledError
from concurrent.futures import CancelledError as futureCancelledError

class FailedProxiedRequest:
    """
    A delegated request that has failed for whatever reason

    The failure context (usually the exception) is stored in the `context`
    property. We also keep track of the proxy URL that serviced the request so
    downstream consumers can make informed retry decisions.
    """

    context = None
    proxy_url = None

    def __init__(self, context=None, proxy_url=None):
        self.context = context
        self.proxy_url = proxy_url


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
    looping = True

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

    def know_hostname(self, url):
        """
        Make sure the hostname is known to this proxy

        This means that we can now keep track of some per-hostname statistics
        for this hostname. If the hostname is not known yet, the statistics are
        re-initialised.

        :param str url:  URL with host name to keep stats for. Case-insensitive.
        :param str:  The host name, as parsed for internal use
        """
        hostname = ural.get_hostname(url).lower()
        if hostname not in self.hostnames:
            self.hostnames[hostname] = namedtuple(
                "HostnameForProxiedRequests", ("running",)
            )
            self.hostnames[hostname].running = []

        return hostname

    def release_cooled_off(self):
        """
        Release proxies that have finished cooling off.

        Proxies cool off for a certain amount of time after starting a request.
        This method removes cooled off requests, so that new ones may fill
        their slot.
        """
        for hostname, metadata in self.hostnames.copy().items():
            for request in metadata.running:
                if (
                    request.status == ProxyStatus.COOLING_OFF
                    and request.timestamp_finished < time.time() - self.COOLOFF
                ):
                    self.log.debug(
                        f"Releasing proxy {self.proxy_url} for host name {hostname}"
                    )
                    self.hostnames[hostname].running.remove(request)

                    # get rid of hostnames with no running or cooling off
                    # requests, else this might grow indefinitely
                    if len(self.hostnames[hostname].running) == 0:
                        del self.hostnames[hostname]

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
        hostname = self.know_hostname(url)

        total_running = sum([len(m.running) for h, m in self.hostnames.items()])
        if total_running >= self.MAX_CONCURRENT_OVERALL:
            return False

        if len(self.hostnames[hostname].running) < self.MAX_CONCURRENT_PER_HOST:
            request = namedtuple(
                "ProxiedRequest",
                ("url", "status", "timestamp_started", "timestamp_finished"),
            )
            request.url = url
            request.status = ProxyStatus.CLAIMED
            request.timestamp_started = 0
            request.timestamp_finished = 0
            self.hostnames[hostname].running.append(request)
            self.log.debug(
                f"Claiming proxy {self.proxy_url} for host name {hostname} ({len(self.hostnames[hostname].running)} of {self.MAX_CONCURRENT_PER_HOST} for host)"
            )
            return self
        else:
            return False

    def mark_request_started(self, url):
        """
        Mark a request for a URL as started

        This updates the status for the related slot. If no matching slot
        exists that is waiting for a request to start running, a `ValueError`
        is raised.

        :param str url:  URL of the proxied request.
        """
        hostname = self.know_hostname(url)

        for i, metadata in enumerate(self.hostnames[hostname].running):
            if metadata.status == ProxyStatus.CLAIMED and metadata.url == url:
                self.hostnames[hostname].running[i].status = ProxyStatus.RUNNING
                self.hostnames[hostname].running[i].timestamp_started = time.time()
                return

        raise ValueError(f"No proxy is waiting for a request with URL {url} to start!")

    def mark_request_finished(self, url):
        """
        Mark a request for a URL as finished

        This updates the status for the related slot. If no matching slot
        exists that is waiting for a request to finish, a `ValueError` is
        raised. After this, the proxy will be marked as cooling off, and is
        released after cooling off is completed.

        :param str url:  URL of the proxied request.
        """
        hostname = self.know_hostname(url)

        for i, metadata in enumerate(self.hostnames[hostname].running):
            if metadata.status == ProxyStatus.RUNNING and metadata.url == url:
                self.hostnames[hostname].running[i].timestamp_finished = time.time()
                self.hostnames[hostname].running[i].status = ProxyStatus.COOLING_OFF
                return

        raise ValueError(f"No proxy is currently running a request for URL {url}!")


class DelegatedRequestHandler:
    queue = {}
    session = None
    proxy_pool = {}
    proxy_settings = {}
    halted = set()
    log = None
    index = 0

    # some magic values
    REQUEST_STATUS_QUEUED = 0
    REQUEST_STATUS_STARTED = 1
    REQUEST_STATUS_WAITING_FOR_YIELD = 2
    PROXY_LOCALHOST = "__localhost__"

    def __init__(self, log, config):
        pool = ThreadPoolExecutor()
        self.session = FuturesSession(executor=pool)
        self.log = log
        
        # Proxy health tracking
        self.proxy_health = {}
        self.proxy_warnings_logged = set()
        self.all_proxies_failed_logged = False

        self.refresh_settings(config)

    def refresh_settings(self, config):
        """
        Load proxy settings

        This is done on demand, so that we do not need a persistent
        configuration reader, which could make things complicated in
        thread-based contexts.

        :param config:  Configuration reader
        """
        # Reset proxy health tracking when settings are refreshed
        num_proxies_restored = len([p for p in self.proxy_health if not self.proxy_health[p]])
        self.proxy_health = {}
        self.proxy_warnings_logged = set()
        self.all_proxies_failed_logged = False
        
        if num_proxies_restored > 0:
            self.log.debug(f"Proxy health reset: {num_proxies_restored} proxies restored")

        self.proxy_settings = {
            k: config.get(k) for k in ("proxies.urls", "proxies.cooloff", "proxies.concurrent-overall",
                                            "proxies.concurrent-host", "proxies.allow-localhost-fallback")
        }

    def add_urls(self, urls, queue_name="_", position=-1, **kwargs):
        """
        Add URLs to the request queue

        :param urls:  An iterable of URLs.
        :param queue_name:  Queue name to add to.
        :param position:  Where in queue to insert; -1 adds to end of queue
        :param kwargs: Other keyword arguments will be passed on to
        `requests.get()`
        """
        if queue_name in self.halted or "_" in self.halted:
            # do not add URLs while delegator is shutting down
            return

        if queue_name not in self.queue:
            self.queue[queue_name] = []

        for i, url in enumerate(urls):
            url_metadata = namedtuple(
                "UrlForDelegatedRequest", ("url", "args", "status", "proxied")
            )
            url_metadata.url = url
            # Make a per-URL copy of kwargs to avoid shared mutation across entries
            per_kwargs = {**kwargs} if kwargs else {}
            url_metadata.index = self.index
            url_metadata.proxied = None
            url_metadata.status = self.REQUEST_STATUS_QUEUED
            self.index += 1

            # If a response hook is provided, wrap it to inject the original URL
            try:
                hooks = per_kwargs.get("hooks")
                if hooks and "response" in hooks:
                    # Copy hooks dict to avoid shared mutation
                    hooks = {**hooks}
                    original_hook = hooks["response"]
                    # Support a single callable or a list of callables
                    def wrap(h, original_url):
                        def _wrapped(resp, *a, **k):
                            # Inject FourCAT-specific original URL in kwargs once
                            if "fourcat_original_url" not in k:
                                k["fourcat_original_url"] = original_url
                            return h(resp, *a, **k)
                        return _wrapped

                    if isinstance(original_hook, list):
                        hooks["response"] = [wrap(h, url) for h in original_hook]
                    else:
                        hooks["response"] = wrap(original_hook, url)

                    # Persist modified hooks back into per-URL kwargs
                    per_kwargs["hooks"] = hooks
            except Exception:
                # If wrapping fails for any reason, proceed without modification
                pass

            # Assign the isolated kwargs to this metadata entry
            url_metadata.kwargs = per_kwargs

            if position == -1:
                self.queue[queue_name].append(url_metadata)
            else:
                self.queue[queue_name].insert(position + i, url_metadata)

        self.manage_requests()

    def get_queue_length(self, queue_name="_"):
        """
        Get the length, of the queue

        :param str queue_name:  Queue name
        :return int: Amount of URLs in the queue (regardless of status)
        """
        queue_length = 0
        for queue in self.queue:
            if queue == queue_name or queue_name == "_":
                queue_length += len(self.queue[queue_name])

        return queue_length

    def claim_proxy(self, url):
        """
        Find a proxy to do the request with

        Finds a `SophisticatedFuturesProxy` that has an open slot for this URL.

        :param str url:  URL to proxy a request for
        :return SophisticatedFuturesProxy, False, or None:
            - SophisticatedFuturesProxy if a proxy is available
            - False if proxies exist but are busy (try again later)
            - None if all proxies are unhealthy (need fallback)
        """
        if not self.proxy_pool:
            # this will trigger the first time this method is called
            # build a proxy pool with some information per available proxy
            proxies = self.proxy_settings["proxies.urls"]
            for proxy_url in proxies:
                self.proxy_pool[proxy_url] = namedtuple(
                    "ProxyEntry", ("proxy", "last_used")
                )
                self.proxy_pool[proxy_url].proxy = SophisticatedFuturesProxy(
                    proxy_url,
                    self.log,
                    self.proxy_settings["proxies.cooloff"],
                    self.proxy_settings["proxies.concurrent-overall"],
                    self.proxy_settings["proxies.concurrent-host"],
                )
                self.proxy_pool[proxy_url].last_used = 0
                # Initialize all proxies as healthy
                self.proxy_health[proxy_url] = True

            self.log.debug(f"Proxy pool has {len(self.proxy_pool)} available proxies.")

        # Filter out unhealthy proxies
        healthy_proxies = [p for p in self.proxy_pool if self.proxy_health.get(p, True)]
        
        # If we have proxies configured but none are healthy, return None
        if self.proxy_pool and not healthy_proxies:
            return None
        
        # within the pool, find the least recently used healthy proxy that is available
        sorted_by_cooloff = sorted(
            healthy_proxies, key=lambda p: self.proxy_pool[p].last_used
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
            for i, url_metadata in enumerate(self.queue[queue_name]):
                url = url_metadata.url

                if url_metadata.status == self.REQUEST_STATUS_WAITING_FOR_YIELD:
                    # waiting to be flushed or passed by `get_result()`
                    continue

                if url_metadata.proxied and url_metadata.proxied.request.done():
                    # collect result and buffer it for yielding
                    # done() here doesn't necessarily mean the request finished
                    # successfully, just that it has returned - a timed out
                    # request will also be done()!
                    self.log.debug(f"Request for {url} finished, collecting result")
                    url_metadata.proxied.proxy.mark_request_finished(url)
                    try:
                        response = url_metadata.proxied.request.result()
                        # annotate the response so processors can see which
                        # proxy (if any) handled the request
                        setattr(
                            response,
                            "_4cat_proxy",
                            url_metadata.proxied.proxy.proxy_url,
                        )
                        url_metadata.proxied.result = response

                    except requests.exceptions.ProxyError as e:
                        # Proxy connection issue - mark proxy as unhealthy and requeue
                        proxy_url = url_metadata.proxied.proxy.proxy_url
                        
                        # Mark this proxy as unhealthy
                        self.proxy_health[proxy_url] = False
                        
                        # Log warning once per proxy
                        if proxy_url not in self.proxy_warnings_logged:
                            self.proxy_warnings_logged.add(proxy_url)
                            self.log.warning(
                                f"Proxy {proxy_url} marked as unhealthy due to connection failure: {str(e)}"
                            )
                        
                        # Reset URL to queued so it will retry with a different proxy
                        url_metadata.status = self.REQUEST_STATUS_QUEUED
                        url_metadata.proxied = None
                        # Don't set to WAITING_FOR_YIELD - let it retry in the normal flow
                    
                    except (
                        ConnectionError,
                        asyncioCancelledError,
                        futureCancelledError,
                        requests.exceptions.RequestException,
                        urllib3.exceptions.HTTPError,
                    ) as e:
                        # this is where timeouts, etc, go
                        url_metadata.proxied.result = FailedProxiedRequest(
                            e, url_metadata.proxied.proxy.proxy_url
                        )

                    finally:
                        # success or fail, we can pass it on
                        # Only set to waiting if not requeued by ProxyError handler
                        if url_metadata.status != self.REQUEST_STATUS_QUEUED:
                            url_metadata.status = self.REQUEST_STATUS_WAITING_FOR_YIELD

                else:
                    # running - ignore for now
                    # could do some health checks here...
                    # logging.debug(f"Request for {url} running...")
                    pass

                if not url_metadata.proxied and not (
                    queue_name in self.halted or "_" in self.halted
                ):
                    # no request running for this URL yet, try to start one
                    proxy = self.claim_proxy(url)
                    
                    if proxy is None:
                        # All proxies are unhealthy - check if localhost fallback is allowed
                        allow_localhost = self.proxy_settings.get("proxies.allow-localhost-fallback", True)
                        
                        if allow_localhost:
                            # Log once that we're falling back to localhost
                            if not self.all_proxies_failed_logged:
                                self.all_proxies_failed_logged = True
                                self.log.error(
                                    "All configured proxies are unhealthy. Falling back to localhost "
                                    "(direct connection) for remaining requests."
                                )
                            
                            # Create/use localhost proxy
                            if self.PROXY_LOCALHOST not in self.proxy_pool:
                                self.proxy_pool[self.PROXY_LOCALHOST] = namedtuple(
                                    "ProxyEntry", ("proxy", "last_used")
                                )
                                self.proxy_pool[self.PROXY_LOCALHOST].proxy = SophisticatedFuturesProxy(
                                    self.PROXY_LOCALHOST,
                                    self.log,
                                    self.proxy_settings["proxies.cooloff"],
                                    self.proxy_settings["proxies.concurrent-overall"],
                                    self.proxy_settings["proxies.concurrent-host"],
                                )
                                self.proxy_pool[self.PROXY_LOCALHOST].last_used = 0
                                self.proxy_health[self.PROXY_LOCALHOST] = True
                            
                            proxy = self.proxy_pool[self.PROXY_LOCALHOST].proxy.claim_for(url)
                            if not proxy:
                                # Localhost proxy busy, try again later
                                continue
                            self.proxy_pool[self.PROXY_LOCALHOST].last_used = time.time()
                        else:
                            # Localhost fallback not allowed - fail the request
                            if not self.all_proxies_failed_logged:
                                self.all_proxies_failed_logged = True
                                self.log.error(
                                    "All configured proxies are unhealthy and localhost fallback is disabled. "
                                    "Remaining requests will fail."
                                )
                            
                            url_metadata.proxied = namedtuple(
                                "DelegatedRequest",
                                ("request", "created", "result", "proxy", "url", "index"),
                            )
                            url_metadata.proxied.result = FailedProxiedRequest(
                                Exception("All proxies unhealthy and localhost fallback disabled"),
                                None
                            )
                            url_metadata.status = self.REQUEST_STATUS_WAITING_FOR_YIELD
                            self.queue[queue_name][i] = url_metadata
                            continue
                    elif proxy is False:
                        # Proxies exist but are busy, try again next loop
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
                        (
                            "request",
                            "created",
                            "result",
                            "proxy",
                            "url",
                            "index",
                        ),
                    )
                    request.created = time.time()
                    request.request = self.session.get(
                        **{
                            "url": url,
                            "timeout": 30,
                            "proxies": proxy_definition,
                            **url_metadata.kwargs
                        }
                    )

                    request.proxy = proxy
                    request.url = url
                    request.index = (
                        url_metadata.index
                    )  # this is to allow for multiple requests for the same URL

                    url_metadata.status = self.REQUEST_STATUS_STARTED
                    url_metadata.proxied = request

                    proxy.mark_request_started(url)

                self.queue[queue_name][i] = url_metadata

    def get_results(self, queue_name="_", preserve_order=True):
        """
        Return available results, without skipping

        Loops through the queue, returning values (and updating the queue) for
        requests that have been finished. If a request is not finished yet,
        stop returning. This ensures that in the end, values are only ever
        returned in the original queue order, at the cost of potential
        buffering.

        :param str queue_name:  Queue name to get results from
        :param bool preserve_order:  Return results in the order they were
        added to the queue. This means that other results are buffered and
        potentially remain in the queue, which may in the worst case
        significantly slow down data collection. For example, if the first
        request in the queue takes a really long time while all other
        requests are already finished, the queue will nevertheless remain
        'full'.

        :return:
        """
        self.manage_requests()

        # no results, no return
        if queue_name not in self.queue:
            return

        # use list comprehensions here to avoid having to modify the
        # lists while iterating through them
        for url_metadata in [u for u in self.queue[queue_name]]:
            # for each URL in the queue...
            if url_metadata.status == self.REQUEST_STATUS_WAITING_FOR_YIELD:
                # see if a finished request is available...
                self.queue[queue_name].remove(url_metadata)
                yield url_metadata.url, url_metadata.proxied.result

            elif preserve_order:
                # ...but as soon as a URL has no finished result, return
                # unless we don't care about the order, then continue and yield
                # as much as possible
                return

    def _halt(self, queue_name="_"):
        """
        Interrupt fetching of results

        Can be used when 4CAT is interrupted. Clears queue and tries to cancel
        running requests.

        Note that running requests *cannot* always be cancelled via `.cancel()`
        particularly when using `stream=True`. It is therefore recommended to
        use `halt_and_wait()` which is blocking until all running requests have
        properly terminated, instead of calling this method directly.

        :param str queue_name:  Queue name to stop fetching results for. By
        default, halt all queues.
        """
        self.halted.add(queue_name)

        for queue in self.queue:
            if queue_name == "_" or queue_name == queue:
                # use a list comprehension here to avoid having to modify the
                # list while iterating through it
                for url_metadata in [u for u in self.queue[queue]]:
                    if url_metadata.status != self.REQUEST_STATUS_STARTED:
                        self.queue[queue].remove(url_metadata)
                    else:
                        url_metadata.proxied.request.cancel()

        self.halted.remove(queue_name)

    def halt_and_wait(self, queue_name="_"):
        """
        Cancel any queued requests and wait until ongoing ones are finished

        Blocking!

        :param str queue_name:  Queue name to stop fetching results for. By
        default, halt all queues.
        """
        self._halt(queue_name)
        while self.get_queue_length(queue_name) > 0:
            # exhaust generator without doing something w/ results
            all(self.get_results(queue_name, preserve_order=False))

        if queue_name in self.queue:
            del self.queue[queue_name]
