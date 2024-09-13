"""
Collect Wikipedia revisions
"""
import requests
import datetime
import ural
import time
import json
import re

from backend.lib.wikipedia_scraper import WikipediaSearch
from common.lib.helpers import UserInput
from common.lib.item_mapping import MappedItem


class SearchWikiRevisions(WikipediaSearch):
    """
    Scrape Wikipedia article revisions
    """
    type = "wikirevs-search"  # job ID
    category = "Search"  # category
    title = "Wikipedia revisions scraper"  # title displayed in UI
    description = "Retrieve metadata for Wikipedia revisions."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI

    # not available as a processor for existing datasets
    accepts = [None]

    options = {
        "intro": {
            "type": UserInput.OPTION_INFO,
            "help": "For a given list of Wikipedia page URLs, retrieve a number of revisions of those pages and their"
                    "metadata. This allows for analysis of how actively an article is edited, and by whom.\n\n"
                    "Note that not all historical versions of a page may be available; for example, if the page has "
                    "been deleted its contents can no longer be retrieved."
        },
        "rvlimit": {
            "type": UserInput.OPTION_TEXT,
            "help": "Number of revisions",
            "min": 1,
            "max": 500,
            "coerce_type": int,
            "default": 50,
            "tooltip": "Number of revisions to collect per page. Cannot be more than 500. Note that pages may have "
                       "fewer revisions than the upper limit you set."
        },
        "urls": {
            "type": UserInput.OPTION_TEXT_LARGE,
            "help": "Wikipedia URLs",
            "tooltip": "Put each URL on a separate line."
        },
        "geolocate": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Attempt to geolocate anonymous edits",
            "tooltip": "Uses the [Abstract](https://www.abstractapi.com/api/ip-geolocation-api) API to link an IP "
                       "address to a geographic location. Note that this makes data collection a lot slower, and that "
                       "locations may be inaccurate and or unavailable for certain IP addresses."
        }
    }

    config = {
        "api.abstract": {
            "type": UserInput.OPTION_TEXT,
            "help": "Abstract API Key",
            "tooltip": "API key for Abstract, the IP geolocation API (used by the Wikipedia revisions scraper)"
        }
    }

    def get_items(self, query):
        """
        Retrieve revisions

        :param dict query:  Search query parameters
        """
        urls = [url.strip() for url in self.parameters.get("urls").split("\n")]
        urls = [url for url in urls if url]
        abstract_api_key = self.config.get("api.abstract")
        location_cache = {}

        num_pages = 0
        num_revisions = 0
        for language, pages in self.normalise_pagenames(urls):
            api_base = f"https://{language}.wikipedia.org/w/api.php"

            for page in pages:
                num_pages += 1

                # get revisions from API
                page_revisions = requests.get(api_base, params={
                    "action": "query",
                    "format": "json",
                    "prop": "revisions",
                    "rvlimit": self.parameters.get("rvlimit"),
                    "titles": page,
                })

                page_revisions = list(page_revisions.json()["query"]["pages"].values())[0]["revisions"]

                self.dataset.update_status(
                    f"Collecting {len(page_revisions):,} revisions for article '{page}' on {language}.wikipedia.org")

                for revision in page_revisions:
                    location = ""

                    # geolocate only anonymous requests
                    if "anon" in revision and abstract_api_key:
                        # todo: check if IPv6 can even be geolocated by abstract
                        # if not, just skip and save the API request
                        location = "UNKNOWN / Geolocation service unavailable"
                        try:
                            # check if cached (to avoid API requests)
                            if revision["user"] in location_cache:
                                location = location_cache[revision["user"]]
                                raise KeyError()  # just to skip the request

                            retries = 0
                            geo = None
                            while retries < 3:
                                # the rate limit is 120 per minute
                                # this should be OK to deal with that
                                geo = requests.get(
                                    f"https://ipgeolocation.abstractapi.com/v1/?api_key={abstract_api_key}&ip_address={revision['user']}",
                                    timeout=5)
                                if geo.status_code == 429:
                                    retries += 1
                                    time.sleep(retries)
                                    continue
                                else:
                                    break

                            # still nothing? give up
                            if not geo:
                                raise TypeError

                            # parse - annoyingly not all properties are always present
                            geo = geo.json()

                            if "region" not in geo:
                                geo["region"] = geo["city"]  # some countries have no region

                            geolocation_bits = []
                            for component in ("continent", "country", "region", "city"):
                                if geo.get(component):
                                    geolocation_bits.append(geo[component])

                            location = " / ".join(geolocation_bits)
                            location_cache[revision["user"]] = location

                        except (json.JSONDecodeError, KeyError, TypeError) as e:
                            pass

                    yield {
                        "title": page,
                        "language": language,
                        "location": location,
                        **revision
                    }
                    num_revisions += 1

        self.dataset.update_status(f"Retrieved {num_revisions:,} revisions for {num_pages:,} page(s).", is_final=True)

    @staticmethod
    def validate_query(query, request, user):
        """
        Validate input for a dataset query

        Will raise a QueryParametersException if invalid parameters are
        encountered. Parameters are additionally sanitised.

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """
        return query

    @staticmethod
    def map_item(item):
        """
        Map collected item

        :param item:  Item collected
        :return MappedItem:  Item mapped for display in CSV files, etc
        """
        timestamp = datetime.datetime.strptime(item["timestamp"], "%Y-%m-%dT%H:%M:%SZ")

        section = ""
        if re.match(r"/\* ([^*]+) \*/", item.get("comment", "")):
            # this is not foolproof, but a nice extra bit of info
            section = re.findall(r"/\* (.*) \*/", item["comment"])[0]

        return MappedItem({
            "id": item["revid"],
            "thread_id": item.get("parentid"),
            "page": item["title"],
            "language": item["language"],
            "url": f"https://{item['language']}.wikipedia.org/w/index.php?title={item['title']}&oldid={item['revid']}",
            "author": item["user"],
            "author_anonymous_location": item.get("location", ""),
            "is_anonymous": "yes" if "anon" in item else "no",
            "is_minor_edit": "yes" if "minor" in item else "no",
            "is_probably_bot": "yes" if item["user"].lower().endswith("bot") else "no", # not foolproof, still useful
            "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "section": section,
            "body": item.get("comment", ""),
            "unix_timestamp": int(timestamp.timestamp())
        })
