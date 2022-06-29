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

import common.config_manager as config
from backend.abstract.search import Search
from common.lib.helpers import UserInput
from common.lib.exceptions import WorkerInterruptedException, QueryParametersException
from datasources.tiktok.search_tiktok import SearchTikTok as SearchTikTokByImport


class SearchTikTokByID(Search):
    """
    Import scraped TikTok data
    """
    type = "tiktok-urls-search"  # job ID
    category = "Search"  # category
    title = "Search TikTok by video URL"  # title displayed in UI
    description = "Retrieve metadata for TikTok video URLs."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_local = False  # Whether this datasource is locally scraped
    is_static = False  # Whether this datasource is still updated

    # not available as a processor for existing datasets
    accepts = [None]

    config = {
        "tiktok-urls.proxies": {
            "type": UserInput.OPTION_TEXT_JSON,
            "default": [],
            "help": "Proxies for TikTok data collection"
        },
        "tiktok-urls.proxies.wait": {
            "type": UserInput.OPTION_TEXT,
            "coerce_type": int,
            "default": 1,
            "help": "Request wait",
            "tooltip": "Time to wait before sending a new request from the same IP"
        }
    }

    options = {
        "intro": {
            "type": UserInput.OPTION_INFO,
            "help": "This data source can retrieve metadata for TikTok videos based on a list of URLs for those "
                    "videos.\n\nEnter a list of TikTok video URLs. Metadata for each video will be extracted from "
                    "each video's page in the browser interface "
                    "([example](https://www.tiktok.com/@willsmith/video/7079929224945093934)). This includes a lot of "
                    "details about the post itself as well as the first 20 comments on the video. The comments and "
                    "much of the metadata is only directly available when downloading the results as an .ndjson file."
        },
        "urls": {
            "type": UserInput.OPTION_TEXT_LARGE,
            "help": "Video URLs",
            "tooltip": "Separate by commas or new lines."
        }
    }

    proxy_map = {}
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive",
        "DNT": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:101.0) Gecko/20100101 Firefox/101.0"
    }

    def get_items(self, query):
        """
        Retrieve metadata for TikTok URLs

        :param dict query:  Search query parameters
        """
        all_proxies = config.get("tiktok-urls.proxies")
        if not all_proxies:
            # no proxies? just request directly
            all_proxies = ["__localhost__"]

        self.proxy_map = {proxy: {
            "busy": False,
            "url": None,
            "next_request": 0
        } for proxy in all_proxies}

        loop = asyncio.new_event_loop()
        return loop.run_until_complete(self.request_metadata(query["urls"].split(",")))

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
        while urls or tiktok_requests:
            # give tasks time to run
            await asyncio.sleep(0)

            available_proxy = [proxy for proxy in self.proxy_map if not
                               self.proxy_map[proxy]["busy"] and self.proxy_map[proxy]["next_request"] <= time.time()]
            available_proxy = available_proxy[0] if available_proxy else None

            if available_proxy and urls:
                url = urls.pop(0)
                url = url.replace("https://", "http://")

                if url in seen_urls:
                    finished += 1
                    self.dataset.log("Skipping duplicate of %s" % url)

                else:
                    proxy = {"http": available_proxy,
                             "https": available_proxy} if available_proxy != "__localhost__" else None
                    tiktok_requests[url] = session.get(url, proxies=proxy, timeout=30)
                    self.proxy_map[available_proxy].update({
                        "busy": True,
                        "url": url
                    })

            if self.interrupted:
                for request in tiktok_requests:
                    request.cancel()

                raise WorkerInterruptedException("Interrupted while fetching TikTok metadata")

            for url in list(tiktok_requests.keys()):
                request = tiktok_requests[url]
                if not request.done():
                    continue

                finished += 1
                seen_urls.add(url)
                used_proxy = [proxy for proxy in self.proxy_map if self.proxy_map[proxy]["url"] == url][0]
                self.proxy_map[used_proxy].update({
                    "busy": False,
                    "next_request": time.time() + config.get("tiktok-urls.proxies.wait", 1)
                })

                exception = request.exception()
                if exception:
                    failed += 1
                    if isinstance(exception, requests.exceptions.RequestException):
                        self.dataset.update_status("Video at %s could not be retrieved (%s: %s)" % (url, type(exception).__name__, exception))
                    else:
                        raise exception

                response = request.result()
                del tiktok_requests[url]

                if response.status_code == 404:
                    failed += 1
                    self.dataset.log("Video at %s no longer exists (404), skipping" % response.url)
                    skip_to_next = True
                    continue

                elif response.status_code != 200:
                    failed += 1
                    self.dataset.update_status(
                        "Received unexpected HTTP response %i for %s, skipping." % (
                            response.status_code, response.url), is_final=True)
                    continue

                soup = BeautifulSoup(response.text, "html.parser")
                sigil = soup.select_one("script#SIGI_STATE")

                if not sigil:
                    failed += 1
                    self.dataset.log("No embedded metadata found for video %s, skipping" % url)
                    continue

                try:
                    metadata = json.loads(sigil.text)
                except json.JSONDecodeError:
                    failed += 1
                    self.dataset.log("Embedded metadata was found for video %s, but it could not be parsed, skipping" % url)
                    continue

                for video in self.reformat_metadata(metadata):
                    self.dataset.update_status("Processed %i of %i TikTok URLs" % (finished, num_urls))
                    self.dataset.update_progress(finished / num_urls)
                    results.append(video)

        if failed > 1:
            self.dataset.update_status("Dataset completed, but not all URLs were available (%i URL(s) failed). See "
                                       "dataset log for details." % failed)

        return results

    def reformat_metadata(self, metadata):
        """
        Take embedded JSON and yield one item per post

        :param dict metadata: Metadata extracted from the TikTok video page
        :return:  Yields one dictionary per video
        """
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

    @staticmethod
    def validate_query(query, request, user):
        """
        Validate TikTok query

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """
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
                    not re.match(r"https?://www\.tiktok\.com/@[^/]+/video/[0-9]+.*", item):
                raise QueryParametersException("'%s' is not a valid TikTok video URL")

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
        return SearchTikTokByImport.map_tiktok_item(item)
