"""
Import scraped TikTok data

It's prohibitively difficult to scrape data from TikTok within 4CAT itself due
to its aggressive rate limiting. Instead, import data collected elsewhere.
"""
import requests
import asyncio
import time
import json
import re

from requests_futures.sessions import FuturesSession
from bs4 import BeautifulSoup

from backend.lib.search import Search
from common.lib.helpers import UserInput
from common.lib.exceptions import WorkerInterruptedException, QueryParametersException, ProcessorException
from datasources.tiktok.search_tiktok import SearchTikTok as SearchTikTokByImport

class SearchTikTokByID(Search):
    """
    Import scraped TikTok data
    """
    type = "tiktok-urls-search"  # job ID
    category = "Search"  # category
    title = "Search TikTok by post URL"  # title displayed in UI
    description = "Retrieve metadata for TikTok post URLs."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_local = False  # Whether this datasource is locally scraped
    is_static = False  # Whether this datasource is still updated

    # not available as a processor for existing datasets
    accepts = [None]

    config = {
        "tiktok-urls-search.proxies": {
            "type": UserInput.OPTION_TEXT_JSON,
            "default": [],
            "help": "Proxies for TikTok data collection"
        },
        "tiktok-urls-search.proxies.wait": {
            "type": UserInput.OPTION_TEXT,
            "coerce_type": float,
            "default": 1.0,
            "help": "Request wait",
            "tooltip": "Time to wait before sending a new request from the same IP"
        }
    }

    @classmethod
    def get_options(cls, parent_dataset=None, config=None) -> dict:
        """
        Get data source options

        :param DataSet parent_dataset:  An object representing the dataset that
            the processor would be or was run on and can be used to show some options
            only to privileged users.
        :param config ConfigManager|None config:  Configuration reader (context-aware)
        """
        return {
            "intro": {
                "type": UserInput.OPTION_INFO,
                "help": "This data source can retrieve metadata for TikTok posts based on a list of URLs for those "
                        "posts.\n\nEnter a list of TikTok post URLs. Metadata for each post will be extracted from "
                        "each post's page in the browser interface "
                        "([example](https://www.tiktok.com/@willsmith/video/7079929224945093934)). This includes a lot of "
                        "details about the post itself such as likes, tags and stickers. Note that some of the metadata is "
                        "only directly available when downloading the results as an .ndjson file."
            },
            "urls": {
                "type": UserInput.OPTION_TEXT_LARGE,
                "help": "Post URLs",
                "tooltip": "Separate by commas or new lines."
            }
        }

    def get_items(self, query):
        """
        Retrieve metadata for TikTok URLs

        :param dict query:  Search query parameters
        """
        tiktok_scraper = TikTokScraper(processor=self, config=self.config)
        loop = asyncio.new_event_loop()
        return loop.run_until_complete(tiktok_scraper.request_metadata(query["urls"].split(",")))

    @staticmethod
    def validate_query(query, request, config):
        """
        Validate TikTok query

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param ConfigManager|None config:  Configuration reader (context-aware)
        :return dict:  Safe query parameters
        """
        if not query.get("urls"):
            # no URLs provided
            raise QueryParametersException("Missing \"Post URLs\" (\"urls\" parameter). Please provide a list of TikTok video URLs.")
        
        # reformat queries to be a comma-separated list with no wrapping
        # whitespace
        whitespace = re.compile(r"\s+")
        items = whitespace.sub("", query.get("urls").replace("\n", ","))

        sanitized_items = []
        # handle telegram URLs
        for item in str(items).split(","):
            if not item.strip():
                continue

            if not re.match(r"https?://www\.tiktokv\.com/share/video/[0-9]+/", item) and \
                    not re.match(r"https?://www\.tiktok\.com/@[^/]+/video/[0-9]+.*", item) and \
                    not re.match(r"https?://tiktok\.com/@[^/]+/video/[0-9]+.*", item):
                raise QueryParametersException("'%s' is not a valid TikTok video URL" % item)

            sanitized_items.append(item)

        # no query 4 u
        if not sanitized_items:
            raise QueryParametersException("You must provide at least one valid TikTok video URL.")

        # simple!
        return {
            "urls": ",".join(sanitized_items)
        }

    @staticmethod
    def map_item(item):
        """
        Analogous to the other TikTok data source

        :param item:
        :return:
        """
        return SearchTikTokByImport.map_item(item)


class TikTokScraper:
    proxy_map = None
    proxy_sleep = 1
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive",
        "DNT": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:101.0) Gecko/20100101 Firefox/101.0"
    }
    last_proxy_update = 0
    last_time_proxy_available = None
    no_available_proxy_timeout = 600
    consecutive_failures = 0

    VIDEO_NOT_FOUND = "oh no, sire, no video was found"

    def __init__(self, processor, config):
        """
        :param Processor processor:  The processor using this function and needing updates
        """
        self.proxy_map = {}
        self.processor = processor

    def update_proxies(self):
        """
        Get proxies that are available

        :return:
        """
        all_proxies = self.processor.config.get("tiktok-urls-search.proxies")
        self.proxy_sleep = self.processor.config.get("tiktok-urls-search.proxies.wait", self.proxy_sleep)
        if not all_proxies:
            # no proxies? just request directly
            all_proxies = ["__localhost__"]

        for proxy in all_proxies:
            if proxy in self.proxy_map:
                continue
            else:
                self.proxy_map[proxy] = {
                    "busy": False,
                    "url": None,
                    "next_request": 0
                }

        for proxy in list(self.proxy_map.keys()):
            if proxy not in all_proxies:
                del self.proxy_map[proxy]

    def get_available_proxies(self):
        """
        Collect proxies from proxy_map that are ready for new requests
        """
        # update proxies every 5 seconds so we can potentially update them
        # while the scrape is running
        if self.last_proxy_update < time.time():
            self.update_proxies()
            self.last_proxy_update = time.time() + 5

        # find out whether there is any connection we can use to send the
        # next request
        available_proxies = [proxy for proxy in self.proxy_map if
                             not self.proxy_map[proxy]["busy"] and self.proxy_map[proxy]["next_request"] <= time.time()]

        if not available_proxies:
            # No proxy available
            if self.last_time_proxy_available is None:
                # First run, possibly issue, but this will allow it to time out
                self.processor.dataset.log("No available proxy found at start of request_metadata")
                self.last_time_proxy_available = time.time()

            if self.last_time_proxy_available + self.no_available_proxy_timeout < time.time():
                # No available proxies in timeout period
                raise ProcessorException(f"Error: No proxy found available after {self.no_available_proxy_timeout}")
        else:
            self.last_time_proxy_available = time.time()

        return available_proxies

    def release_proxy(self, url):
        """
        Release a proxy to be used later
        """
        # Release proxy
        used_proxy = [proxy for proxy in self.proxy_map if self.proxy_map[proxy]["url"] == url]
        if used_proxy:
            used_proxy = used_proxy[0]
            self.proxy_map[used_proxy].update({
                "busy": False,
                "next_request": time.time() + self.proxy_sleep
            })
        else:
            # TODO: why are we releasing a proxy without a URL?
            self.processor.dataset.log(f"Unable to find and release proxy associated with {url}")
            pass

    async def request_metadata(self, urls):
        """
        Request TikTok metadata for a list of URLs

        Uses asyncio to request URLs concurrently if proxy servers are
        available. Returns a list of metadata, one object per video.

        :param list urls:  URLs to collect data for
        :return list:  Metadata
        """
        session = FuturesSession()
        session.headers.update(self.headers)
        tiktok_requests = {}
        finished = 0
        num_urls = len(urls)
        seen_urls = set()

        results = []
        failed = 0
        dupes = 0
        retries = {}

        while urls or tiktok_requests:
            # give tasks time to run
            await asyncio.sleep(0.1)

            available_proxies = self.get_available_proxies()

            for available_proxy in available_proxies:
                url = None
                while urls and url is None:
                    url = urls.pop(0)
                    url = url.replace("https://", "http://")  # https is finicky, lots of blocks

                    # Check if url already collected or should be retried
                    if url in seen_urls and url not in retries:
                        finished += 1
                        dupes += 1
                        self.processor.dataset.log("Skipping duplicate of %s" % url)
                        url = None
                        continue

                    # Add url to be collected
                    self.processor.dataset.log(f"Requesting: {url}")
                    proxy = {"http": available_proxy,
                             "https": available_proxy} if available_proxy != "__localhost__" else None
                    tiktok_requests[url] = session.get(url, proxies=proxy, timeout=30)
                    seen_urls.add(url)
                    self.proxy_map[available_proxy].update({
                        "busy": True,
                        "url": url
                    })

            # wait for async requests to end (after cancelling) before quitting
            # the worker
            if self.processor.interrupted:
                for request in tiktok_requests.values():
                    request.cancel()

                max_timeout = time.time() + 20
                while not all([r for r in tiktok_requests.values() if r.done()]) and time.time() < max_timeout:
                    await asyncio.sleep(0.5)

                raise WorkerInterruptedException("Interrupted while fetching TikTok metadata")

            # handle received data
            for url in list(tiktok_requests.keys()):
                request = tiktok_requests[url]
                if not request.done():
                    continue

                finished += 1
                self.release_proxy(url)

                # handle the exceptions we know to expect - else just raise and
                # log
                exception = request.exception()
                if exception:
                    failed += 1
                    if isinstance(exception, requests.exceptions.RequestException):
                        self.processor.dataset.update_status(
                            "Video at %s could not be retrieved (%s: %s)" % (url, type(exception).__name__, exception))
                    else:
                        raise exception

                # retry on requestexceptions
                try:
                    response = request.result()
                except requests.exceptions.RequestException:
                    if url not in retries or retries[url] < 3:
                        if url not in retries:
                            retries[url] = 0
                        retries[url] += 1
                        urls.append(url)
                    continue
                finally:
                    del tiktok_requests[url]

                # video may not exist
                if response.status_code == 404:
                    failed += 1
                    self.processor.dataset.log("Video at %s no longer exists (404), skipping" % response.url)
                    continue

                # haven't seen these in the wild - 403 or 429 might happen?
                elif response.status_code != 200:
                    failed += 1
                    self.processor.dataset.update_status(
                        "Received unexpected HTTP response %i for %s, skipping." % (response.status_code, response.url))
                    continue

                # now! try to extract the JSON from the page
                soup = BeautifulSoup(response.text, "html.parser")
                sigil = soup.select_one("script#SIGI_STATE")

                if not sigil:
                    # alternatively, the JSON is here
                    sigil = soup.select_one("script#__UNIVERSAL_DATA_FOR_REHYDRATION__")

                if not sigil:
                    if url not in retries or retries[url] < 3:
                        if url not in retries:
                            retries[url] = 0
                        retries[url] += 1
                        urls.append(url)
                        self.processor.dataset.log("No embedded metadata found for video %s, retrying" % url)
                    else:
                        failed += 1
                        self.processor.dataset.log("No embedded metadata found for video %s, skipping" % url)
                    continue

                try:
                    if sigil.text:
                        metadata = json.loads(sigil.text)
                    elif sigil.contents and len(sigil.contents) > 0:
                        metadata = json.loads(sigil.contents[0])
                    else:
                        failed += 1
                        self.processor.dataset.log(
                            "Embedded metadata was found for video %s, but it could not be parsed, skipping" % url)
                        continue
                except json.JSONDecodeError:
                    failed += 1
                    self.processor.dataset.log(
                        "Embedded metadata was found for video %s, but it could not be parsed, skipping" % url)
                    continue

                for video in self.reformat_metadata(metadata):
                    if video == self.VIDEO_NOT_FOUND:
                        failed += 1
                        self.processor.dataset.log(f"Video for {url} not found, may have been removed, skipping")
                        continue

                    if not video.get("stats") or video.get("createTime") == "0":
                        # sometimes there are empty videos? which seems to
                        # indicate a login wall

                        self.processor.dataset.log(
                            f"Empty metadata returned for video {url} ({video['id']}), skipping. This likely means that the post requires logging in to view.")
                        continue
                    else:
                        results.append(video)

                    self.processor.dataset.update_status("Processed %s of %s TikTok URLs" %
                                               ("{:,}".format(finished), "{:,}".format(num_urls)))
                    self.processor.dataset.update_progress(finished / num_urls)

        notes = []
        if failed:
            notes.append("%s URL(s) failed or did not exist anymore" % "{:,}".format(failed))
        if dupes:
            notes.append("skipped %s duplicate(s)" % "{:,}".format(dupes))

        if notes:
            self.processor.dataset.update_status("Dataset completed, but not all URLs were collected (%s). See "
                                       "dataset log for details." % ", ".join(notes))

        return results

    def reformat_metadata(self, metadata):
        """
        Take embedded JSON and yield one item per post

        :param dict metadata: Metadata extracted from the TikTok video page
        :return:  Yields one dictionary per video
        """
        # may need some extra parsing to find the item data...
        if "__DEFAULT_SCOPE__" in metadata and "webapp.video-detail" in metadata["__DEFAULT_SCOPE__"]:
            try:
                video = metadata["__DEFAULT_SCOPE__"]["webapp.video-detail"]["itemInfo"]["itemStruct"]
            except KeyError as e:
                if "statusCode" in metadata["__DEFAULT_SCOPE__"]["webapp.video-detail"]:
                    yield self.VIDEO_NOT_FOUND
                    return
                else:
                    raise e.__class__ from e

            metadata = {"ItemModule": {
                video["id"]: video
            }}

        if "ItemModule" in metadata:
            for video_id, item in metadata["ItemModule"].items():
                if "CommentItem" in metadata:
                    comments = {i: c for i, c in metadata["CommentItem"].items() if c["aweme_id"] == video_id}
                    if "UserModule" in metadata:
                        for comment_id in list(comments.keys()):
                            username = comments[comment_id]["user"]
                            comments[comment_id]["user"] = metadata["UserModule"].get("users", {}).get(username,
                                                                                                       username)
                else:
                    comments = {}

                yield {**item, "comments": list(comments.values())}
