"""
Retrieve HTML title (and other metadata) for URLs
"""
import csv

from backend.lib.processor import BasicProcessor
from common.lib.helpers import UserInput
from common.lib.exceptions import ProcessorInterruptedException

import requests
import warnings
import urllib3
import asyncio
import time
import ural

from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning
from requests_futures.sessions import FuturesSession
from concurrent.futures import ThreadPoolExecutor

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class URLFetcher(BasicProcessor):
    """
    Retrieve HTML title (and other metadata) for URLs
    """
    type = "url-metadata"  # job type ID
    category = "Post metrics"  # category
    title = "Fetch URL metadata"  # title displayed in UI
    description = ("Fetches the page title and other metadata for URLs referenced in the dataset. Makes a request to "
                   "each URL, optionally following HTTP redirects.")  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    followups = []

    options = {
        "columns": {
            "type": UserInput.OPTION_TEXT,
            "help": "Column(s) to get URLs from",
            "default": "body"
        },
        "follow-redirects": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Follow redirects?",
            "default": True,
            "tooltip": "Follow HTTP redirects (status 301 or 302) and report on the URL redirected to instead of the "
                       "original URL"
        },
        "ignore-duplicates": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Ignore duplicates?",
            "default": True,
            "tooltip": "If enabled, only include the first occurrence of a URL. Otherwise, a row will be included in "
                       "the output CSV file for each separate occurrence of the URL. Note that each URL is only "
                       "requested once regardless."
        }
    }

    # todo: find a way to share proxy pool with other processors using proxies
    config = {
        "url-metadata.proxies": {
            "type": UserInput.OPTION_TEXT_JSON,
            "default": [],
            "help": "Proxies for TikTok data collection"
        },
        "url-metadata.proxies.wait": {
            "type": UserInput.OPTION_TEXT,
            "coerce_type": float,
            "default": 1.0,
            "help": "Request wait",
            "tooltip": "Time to wait before sending a new request from the same IP"
        },
        "url-metadata.timeout": {
            "type": UserInput.OPTION_TEXT,
            "coerce_type": float,
            "default": 60.0,
            "help": "Timeout",
            "tooltip": "Time to wait before cancelling a request and potentially trying again"
        }
    }

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        Get processor options

        This method by default returns the class's "options" attribute, or an
        empty dictionary. It can be redefined by processors that need more
        fine-grained options, e.g. in cases where the availability of options
        is partially determined by the parent dataset's parameters.

        :param DataSet parent_dataset:  An object representing the dataset that
        the processor would be run on
        :param User user:  Flask user the options will be displayed for, in
        case they are requested for display in the 4CAT web interface. This can
        be used to show some options only to privileges users.
        """
        options = cls.options

        if parent_dataset and parent_dataset.get_columns():
            columns = parent_dataset.get_columns()
            options["columns"]["type"] = UserInput.OPTION_MULTI
            options["columns"]["inline"] = True
            options["columns"]["options"] = {v: v for v in columns}
            options["columns"]["default"] = ["body"]

        return options

    def process(self):
        """
        Extracts URLs from the dataset, fetches metadata for each URL, and
        writes the results to a CSV file
        """

        columns = self.parameters.get("columns")
        follow_redirects = self.parameters.get("follow-redirects")
        ignore_dupes = self.parameters.get("ignore-duplicates")
        if type(columns) is not list:
            columns = [columns]

        # first fetch all URLs from the dataset
        all_urls = {}

        # we're not interested in verifying certificates
        # we *should* be, properly, but the chance of encountering a bad
        # certificate is relatively high, and we want to get metadata in that
        # case as well
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        warnings.simplefilter("ignore", category=MarkupResemblesLocatorWarning)

        self.dataset.update_status("Finding URLs in dataset")
        for item in self.source_dataset.iterate_items(self):
            # combine column contents that we need to extract URLs from
            source_text = " ".join([item[column] for column in columns])
            urls = ural.urls_from_text(source_text)

            for url in urls:
                if url not in all_urls:
                    all_urls[url] = {
                        "items": [],
                        "retries": 0,
                        "retry_after": 0
                    }
                elif ignore_dupes:
                    continue

                # we're only going to request each URL once, but they might be
                # used in multiple items. so save references to all items per
                # URL; save item ID and timestamp, which we will include in the
                # output later
                all_urls[url]["items"].append({k: v for k, v in item.items() if k in ("id", "thread_id", "timestamp")})

        # now start fetching things
        with self.dataset.get_results_path().open("w", newline="") as outfile:
            fieldnames = ("item_id", "thread_id", "item_timestamp", "url", "final_url", "domain_name", "status",
                          "status_code", "reason", "title")

            self.writer = csv.DictWriter(outfile, fieldnames=fieldnames)
            self.writer.writeheader()

            loop = asyncio.new_event_loop()
            urls_failed, urls_success = loop.run_until_complete(self.fetch_urls(all_urls, follow_redirects))

        # log warning if not everything succeeded
        if urls_failed:
            self.dataset.update_status(f"URLs fetched, but {urls_failed:,} URL(s) could not be retrieved. See dataset "
                                       f"log for details.", is_final=True)

        # and write everything to a CSV
        self.dataset.finish(urls_failed + urls_success)
        self.job.finish()

    async def fetch_urls(self, urls, follow_redirects):
        """
        Fetch URLs

        This is a bit more complicated than you might expect because we want
        to be able to parallelise requests. To do so we use futures, assigning
        futures to proxies as they become available and then later checking
        whether requests have been completed and saving the results.

        :param dict urls:  URLs to fetch, as defined by `process()`.
        :param bool follow_redirects:  Follow HTTP redirects?
        :return list:  Lists of dictionaries, to write to a result CSV
        """
        results = []
        pool = ThreadPoolExecutor()

        proxy_cooloff = self.config.get("url-metadata.proxies.wait", 1)
        max_retries = 3
        looping = True
        total_urls = len(urls)
        previous_done = 0
        urls_success = 0
        urls_failed = 0

        self.update_proxies()

        while looping:
            # tasks are only actually executed when something is awaited! so
            # we need this 'dummy' await just to have some sort of blocking
            # action during which futures can be executed
            # according to the docs, asyncio.sleep(0) is made for that scenario
            # but it seems that that doesn't give long enough for things to
            # complete sometimes, so 0.1 it is
            await asyncio.sleep(0.1)

            # progress needs some math, since we're not doing things sequentially
            done = urls_success + urls_failed
            if done > previous_done:
                previous_done = done
                self.dataset.update_status(f"Processed {done:,}/{total_urls:,} URLs")
                self.dataset.update_progress(done / total_urls)

            # clean up futures before halting on interrupt
            if self.interrupted:
                for p, info in self.proxy_map.items():
                    if not info["available"] and info["request"]:
                        info["request"].cancel()

                raise ProcessorInterruptedException()

            # figure out which URLs are currently being requested
            urls_busy = [p["url"] for p in self.proxy_map.values() if not p["available"]]

            # loop through remaining URLs to start requests if possible
            for url, url_info in urls.items():
                if url in urls_busy:
                    # skip if already being requested
                    continue

                if url_info["retry_after"] > time.time():
                    # skip if queued for retry, but not yet
                    continue

                available_proxies = [p for p, info in self.proxy_map.items() if info["available"] and info["next_request"] <= time.time()]
                if not available_proxies:
                    # all proxies are busy, skip...
                    break

                # run request
                session = FuturesSession(executor=pool)
                chosen_proxy = available_proxies[0]

                proxy_url = chosen_proxy
                proxy_url += ":3128" if ":" not in chosen_proxy else ""
                proxy_url = {"http": proxy_url, "https": proxy_url} if chosen_proxy != "__localhost__" else None

                if url.split("/")[2] == "t.co":
                    # t.co only uses HTTP redirect when not using a browser UA
                    ua = "4cat-bot/0.0 (4cat.nl)"
                else:
                    # but for most other sites a browser UA works better!
                    ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0"

                self.proxy_map[chosen_proxy].update({
                    "available": False,
                    "start_request": time.time(),
                    "url": url,
                    "session": session,
                    "request": session.get(url, headers={
                        "User-Agent": ua
                    }, hooks={
                        # use hooks to download the content (stream=True) in parallel
                        "response": URLFetcher.stream_url
                    }, verify=False, proxies=proxy_url, timeout=self.config.get("url-metadata.timeout", 70),
                                           allow_redirects=follow_redirects, stream=True)
                })

            # now loop through all proxies to see if any requests were completed
            for proxy, status in self.proxy_map.items():
                if status["available"]:
                    # not running a request at the moment
                    continue

                if not status["request"].done():
                    # request in progress at the moment
                    if status["start_request"] < time.time() - self.config.get("url-metadata.timeout", 70):
                        # busy too long: cancel request, will be handled as a TimeoutError later
                        status["request"].cancel()
                    else:
                        continue

                # mark used proxy as available again (after a small wait)
                self.proxy_map[proxy].update({
                    "available": True,
                    "next_request": time.time() + proxy_cooloff
                })

                # error - could be that the site doesn't exist or timed out
                # self.dataset.log(f"Reading result for {status['url']}")
                try:
                    if status["request"].cancelled():
                        raise TimeoutError()
                    else:
                        try:
                            response = status["request"].result()
                        except UnicodeDecodeError:
                            # this happens if a Location header is detected but
                            # the requests library cannot parse its content
                            # seems like a bug in requests, but it is very rare
                            # so we take the L and note it as a connection
                            # error
                            raise requests.exceptions.InvalidHeader("HTTP Redirect using unknown encoding")

                except (
                ConnectionError, requests.exceptions.RequestException, urllib3.exceptions.HTTPError, TimeoutError) as e:
                    self.proxy_map[proxy].update({
                        # use a big cooloff just in case the IP is
                        # getting blocked or something
                        "next_request": time.time() + (proxy_cooloff * 15)
                    })
                    self.proxy_map[proxy]["request"] = None

                    if urls[status["url"]]["retries"] < max_retries:
                        urls[status["url"]]["retries"] += 1
                        urls[status["url"]]["retry_after"] = time.time() + proxy_cooloff
                        self.dataset.log(
                            f"Error getting URL {status['url']} ({str(e)}), trying again in {proxy_cooloff} seconds")
                    else:
                        self.dataset.log(
                            f"Error getting URL {status['url']} ({str(e)}), exceeded max retries, writing error and moving on")
                        for item in urls[status["url"]]["items"]:
                            self.writer.writerow({
                                "item_id": item["id"],
                                "thread_id": item["thread_id"],
                                "item_timestamp": item["timestamp"],
                                "url": status["url"],
                                "final_url": "",
                                "domain_name": "",
                                "status": "error",
                                "status_code": 0,
                                "reason": e.__class__.__name__,
                                "title": ""
                            })

                        del urls[status["url"]]
                        urls_failed += 1

                    continue

                # we have a response!
                for item in urls[status["url"]]["items"]:
                    self.writer.writerow({
                        "item_id": item["id"],
                        "thread_id": item["thread_id"],
                        "item_timestamp": item["timestamp"],
                        "url": status["url"],
                        "final_url": response.url,
                        "domain_name": ural.get_domain_name(response.url),
                        "status": "success",
                        "status_code": response.status_code,
                        "reason": response.reason,
                        "title": response.page_title
                    })

                del urls[status["url"]]
                urls_success += 1

            # out of URLs? stop working
            if not urls:
                looping = False

        return urls_failed, urls_success

    def update_proxies(self):
        """
        Update proxy map

        This is used to create a proxy map from the list of configured proxies.
        If no proxy list is configured, or if it is empty, use localhost as a
        proxy, i.e. just send requests as normal.
        """
        configured_proxies = self.config.get("url-metadata.proxies", [])
        if not configured_proxies:
            configured_proxies.append("__localhost__")

        self.proxy_map = {
            proxy: {
                "available": True,
                "next_request": 0,
                "url": "",
                "start_request": 0,
                "session": None,
                "request": None
            } for proxy in configured_proxies
        }

    @staticmethod
    def stream_url(response, *args, **kwargs):
        """
        Helper function for fetch_urls

        To avoid very large responses clogging up the processor, we use this
        for a requests hook to only download that part of the response needed
        to determine the page title.

        We store the title in the (custom) 'page_title' property of the
        response.

        :param requests.Response response: requests response object
        """
        response._content_consumed = True
        response._content = ""
        response.page_title = ""

        # we set _content_consumed and _content here because if not, requests
        # will (in some situations) attempt to read more of the data later when
        # resolving result() on the future of the request, and that will not
        # end well

        if not response.encoding and not response.ok:
            return

        # we don't know where in the page the title tag is
        # so read in chunks until we find one (or we hit the max)
        preamble = bytes()

        while len(preamble) < 500000:
            chunk = response.raw.read(1024, decode_content=True)
            if not chunk:
                break

            preamble += chunk
            soup = BeautifulSoup(preamble, "lxml")
            if soup.title and soup.title.text:
                response.page_title = soup.title.text
                break

        response.raw.close()
        response._content = preamble
