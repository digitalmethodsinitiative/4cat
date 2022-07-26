"""
Search Parler

Scrape parler posts via the Parler web API
"""
import requests
import datetime
import json
import time
import re

from backend.abstract.search import Search
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException
from common.lib.helpers import UserInput


class SearchParler(Search):
    """
    Parler scraper
    """
    type = "parler-search"  # job ID
    category = "Search"  # category
    title = "Search Parler"  # title displayed in UI
    description = "Retrieve Parler posts by user or hashtag, in chronological order"  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI
    is_local = False    # Whether this datasource is locally scraped
    is_static = False   # Whether this datasource is still updated

    # not available as a processor for existing datasets
    accepts = [None]

    # let's not get rate limited
    max_workers = 1

    options = {
        "intro": {
            "type": UserInput.OPTION_INFO,
            "help": "Posts are scraped in reverse chronological order; the most recent post for a given query will be "
                    "scraped first. Note that you will need a Parler account to use this data source. Unfortunately "
                    "Parler only provides approximate timestamps in the format of '1 week ago' et cetera, so scraped "
                    "timestamps are estimates that get less accurate for older posts."
        },
        "intro-2": {
            "type": UserInput.OPTION_INFO,
            "help": "You can scrape up to **fifteen** items at a time. Separate the items with commas or blank lines. "
                    "Enter hashtags and/or user names; make sure to include the `#` prefix for hashtags! Note that for "
                    "hashtags, only the 20 most recent posts can be scraped."
        },
        "query": {
            "type": UserInput.OPTION_TEXT_LARGE,
            "help": "Items to scrape",
            "tooltip": "Separate with commas or new lines."
        },
        "max_posts": {
            "type": UserInput.OPTION_TEXT,
            "help": "Posts per item",
            "min": 1,
            "max": 2500,
            "default": 10
        },
        "scrape_echoes": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Include echoes",
            "tooltip": "Echoes are Parler's equivalent to Twitter's retweets",
            "default": False
        },
        "divider": {
            "type": UserInput.OPTION_DIVIDER
        },
        "intro-token": {
            "type": UserInput.OPTION_INFO,
            "help": "The following values must be obtained from your browser after logging in on Parler. Then press "
                    "F12 to open the Inspector, go to the 'Storage' tab in the panel that appears, and then open the "
                    "entry for 'parler.com' under 'Cookies' in the Storage panel. Copy the value for "
                    "'parler_auth_token', which looks like a long string of letters and numbers."
        },
        "token": {
            "type": UserInput.OPTION_TEXT,
            "help": "Auth token",
            "cache": True,
            "sensitive": True
        },

    }

    def get_items(self, query):
        """
        Run custom search

        Fetches data from Parler via instaloader.
        """

        # ready our parameters
        parameters = self.dataset.get_parameters()
        max_posts = parameters.get("items", 100)
        queries = [query.strip() for query in parameters.get("query", "").split(",")]
        scrape_echoes = parameters.get("scrape_echoes", False)
        num_query = 0

        # start a HTTP session. Parler uses two session 'cookies' that are required on each request, else no response
        # will be given. These can only be obtained by logging in. Logging in via 4CAT is not preferred, because it will
        # lead to quick rate limiting and requires people to share their passwords. Instead, ask users to obtain these
        # values by logging in themselves.
        session = requests.Session()
        session.cookies.set("parler_auth_token", parameters.get("token", ""))
        session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:84.0) Gecko/20100101 Firefox/84.0"

        for query in queries:
            if not query.strip():
                continue

            num_query += 1
            query = query.strip()
            is_hashtag = (query[0] == "#")

            if is_hashtag:
                params = {"tag": query[1:]}
                url = "https://parler.com/pages/hashtags.php"
            else:
                params = {"user": query}
                url = "https://parler.com/pages/feed.php"

            num_posts = 0
            page = 1
            known_posts = set()
            fetching = True
            while fetching:
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while scraping Parler")

                try:
                    params[page] = page
                    chunk_posts = session.post(url, data=params)
                    page += 1

                    if chunk_posts.status_code in (404, 400):
                        # no results
                        break

                    if chunk_posts.status_code != 200:
                        # no results
                        self.dataset.update_status(
                            "Got unexpected status from Parler API (%i) - cannot parse data, halting." % chunk_posts.status_code,
                            is_final=True)
                        return

                    chunk_posts = chunk_posts.json()
                except json.JSONDecodeError:
                    # this would be weird
                    self.dataset.update_status("Got unexpected response from Parler API - cannot parse data, halting.",
                                               is_final=True)
                    return
                except (requests.RequestException, ConnectionError):
                    # this would be weird
                    self.dataset.update_status("Error connecting to Parler - halting.", is_final=True)
                    return

                if not chunk_posts:
                    fetching = False
                    break

                for post in chunk_posts:
                    if post.get("ad"):
                        # skip ads
                        continue

                    if post["primary"]["id"] in known_posts:
                        # if we see repeating posts we're at the end
                        fetching = False
                        break

                    known_posts.add(post["primary"]["id"])

                    # for echoes, the main post is mostly empty, and the
                    # content of the echoed post is enclosed - we mostly use
                    # the content of the echoed post
                    is_echo = False
                    if post["primary"].get("is_echo") and not scrape_echoes:
                        continue
                    elif post["primary"].get("is_echo"):
                        is_echo = True
                        post_src = post["parent"]
                    else:
                        post_src = post["primary"]

                    post_src["badges"] = json.dumps(post_src["badges"])

                    mapped_post = {
                        "id": post_src["id"],
                        "thread_id": post_src["id"],
                        "subject": post_src.get("title", "") if post_src.get("title") else "",
                        "body": post_src.get("full_body", post_src.get("body", "")),
                        "author": post_src["username"],
                        "author_fullname": post_src["name"],
                        "timestamp": self.get_timedelta(post["primary"]),  # for echoes, time at which it was echoed
                        "timestamp_ago": post["primary"]["time_ago"],
                        "comments": post_src["commentCount"],
                        "echoes": post_src["echoCount"],
                        "votes": post_src["voteCount"],
                        "image_url": post_src.get("image", ""),
                        "video_url": post_src["video_data"]["videoSrc"] if post_src["has_video"] else "",
                        "linked_urls": post_src.get("long_link"),
                        "is_echo": "yes" if is_echo else "no",
                        "is_sensitive": "yes" if bool(post_src["sensitive"]) else "no",
                        "is_video": "yes" if bool(post_src["has_video"]) else "no",
                        "echoed_by": "",
                        "echoed_timestamp": "",
                        "echoed_timestamp_ago": "",
                    }

                    if is_echo:
                        # for echoes, add some extra metadata: the echo'ing
                        # user and the timestamp of the echoed post
                        mapped_post["echoed_by"] = post["primary"]["username"]
                        mapped_post["echoed_timestamp"] = self.get_timedelta(post["parent"])
                        mapped_post["echoed_timestamp_ago"] = post["parent"]["time_ago"]

                    num_posts += 1
                    yield mapped_post

                    if num_posts >= max_posts:
                        fetching = False
                        break

                self.dataset.update_status(
                    "Retrieved %i posts for query '%s' (%i/%i)" % (num_posts, query, num_query, len(queries)))

                time.sleep(1.5)

    def validate_query(query, request, user):
        """
        Validate Parler query input

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """
        # no query 4 u
        if not query.get("query", "").strip():
            raise QueryParametersException("You must provide a search query.")

        if not query.get("token"):
            raise QueryParametersException("You must provide an access token.")

        # mostly arbitrary - may need tweaking
        max_posts = 2500
        if query.get("max_posts", ""):
            try:
                max_posts = min(abs(int(query.get("max_posts"))), max_posts)
            except TypeError:
                raise QueryParametersException("Provide a valid number of posts to query.")

        # reformat queries to be a comma-separated list with no wrapping
        # whitespace
        whitespace = re.compile(r"\s+")
        items = whitespace.sub("", query.get("query").replace("\n", ","))
        if len(items.split(",")) > 15:
            raise QueryParametersException("You cannot query more than 15 items at a time.")

        # simple!
        return {
            "items": max_posts,
            "query": items,
            "token": query.get("token"),
            "scrape_echoes": bool(query.get("scrape_echoes", False))
        }

    def get_timedelta(self, post):
        """
        Get timestamp based on delta time

        Parler doesn't return precise timestamps, only e.g. "1 week ago".
        This function returns a precise timestamp based on that on a best
        effort basis, e.g. '1 week ago' would give the current timestamp
        minus one week.

        :param dict post:  Post to get timestamp from
        :return int:  Extrapolated unix timestamp
        """
        unit = re.sub(r"[0-9]", "", post["time_ago"]).lower()
        amount = int(re.sub(r"[^0-9]", "", post["time_ago"]))

        if unit == "d":
            delta = datetime.timedelta(days=amount)
        elif unit == "w":
            delta = datetime.timedelta(weeks=amount)
        elif unit == "mo":
            delta = datetime.timedelta(days=amount * 30.5)
        elif unit == "y":
            delta = datetime.timedelta(days=amount * 365.25)
        else:
            delta = datetime.timedelta()

        return int((datetime.datetime.now() - delta).timestamp())
