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

    # not available as a processor for existing datasets
    accepts = [None]

    # let's not get rate limited
    max_workers = 1

    options = {
        "intro": {
            "type": UserInput.OPTION_INFO,
            "help": "Posts are scraped in reverse chronological order; the most recent post for a given query will be "
                    "scraped first. Note that you will need a Parler account to use this data source.\n\nYou can "
                    "scrape up to **fifteen** items at a time. Separate the items with commas or blank lines. Enter "
                    "hashtags and/or user names; make sure to include the `#` prefix for hashtags!"
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
        "daterange": {
            "type": UserInput.OPTION_DATERANGE,
            "help": "Date range"
        },
        "divider": {
            "type": UserInput.OPTION_DIVIDER
        },
        "intro-jst-mst": {
            "type": UserInput.OPTION_INFO,
            "help": "The following values can be obtained by logging in on Parler, then (in Chrome or Firefox) "
                    "right-clicking on the page, and choosing 'Inspect Element'. In the panel that pops up, navigate "
                    "to the 'Storage' tab. You will find 'jst' and 'mst' listed there; copy their values below."
        },
        "jst": {
            "type": UserInput.OPTION_TEXT,
            "help": "JST",
            "cache": True,
            "sensitive": True
        },
        "mst": {
            "type": UserInput.OPTION_TEXT,
            "help": "MST",
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
        min_timestamp = parameters.get("min_date", 0)
        max_timestamp = parameters.get("max_date", time.time())
        queries = [query.strip() for query in parameters.get("query", "").split(",")]
        scrape_echoes = parameters.get("scrape_echoes", False)
        num_query = 0

        # start a HTTP session. Parler uses two session 'cookies' that are required on each request, else no response
        # will be given. These can only be obtained by logging in. Logging in via 4CAT is not preferred, because it will
        # lead to quick rate limiting and requires people to share their passwords. Instead, ask users to obtain these
        # values by logging in themselves.
        session = requests.Session()
        session.cookies.set("mst", parameters.get("mst", ""))
        session.cookies.set("jst", parameters.get("jst", ""))
        session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:84.0) Gecko/20100101 Firefox/84.0"

        user_map = {}
        ref_map = {}
        seen_parleys = set()

        for query in queries:
            if not query.strip():
                continue

            num_query += 1
            query = query.strip()
            is_hashtag = (query[0] == "#")

            if is_hashtag:
                params = {"tag": query[1:], "limit": 100}
                url = "https://api.parler.com/v1/post/hashtag"
            else:
                # for user queries, we need the user ID, which is *not* the username and can only be obtained
                # via the API
                try:
                    user_id_src = self.request_from_parler(session, "GET", "https://api.parler.com/v1/profile", data={"username": query})
                    user_id = user_id_src["_id"]
                except KeyError:
                    # user does not exist or no results
                    continue
                except json.JSONDecodeError as e:
                    self.log.warning("%s:\n\n%s" % (e, user_id_src.text))
                    continue
                params = {"id": user_id, "limit": 100}
                url = "https://api.parler.com/v1/post/creator"

            cursor = ""
            num_posts = 0
            while True:
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while scraping Parler")

                if cursor:
                    # handles pagination
                    params["startkey"] = cursor

                try:
                    chunk_posts = self.request_from_parler(session, "GET", url, data=params)

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

                if "posts" not in chunk_posts:
                    self.log.warning(repr(chunk_posts))
                    break

                for user in chunk_posts.get("users", {}):
                    user_map[user["id"]] = user["username"]

                for ref in chunk_posts.get("postRefs", {}):
                    ref_map[ref["_id"]] = ref


                done = False
                for post in chunk_posts["posts"]:
                    # fairly straighforward - most of the API response maps 1-on-1 to 4CAT data fields
                    # in case of reposts (echoes), use the original data and mark it as a repost
                    if post.get("source_dataset") and int(post.get("depth", 0)) == 1:
                        if not scrape_echoes:
                            continue

                        reposted_by = user_map.get(post["creator"])
                        post_src = ref_map[post.get("source_dataset")]
                    else:
                        reposted_by = ""
                        post_src = post

                    if post_src["_id"] in seen_parleys:
                        # items may be scraped twice e.g. when querying two
                        # separate hashtags that are both used in a single
                        # parley - so keep track of seen parleys and skip
                        continue

                    seen_parleys.add(post_src["_id"])

                    dt = datetime.datetime.strptime(post["createdAt"], "%Y%m%d%H%M%S")
                    post = {
                        "id": post_src["_id"],
                        "thread_id": post_src["_id"],
                        "subject": "",
                        "body": post_src["body"],
                        "author": user_map.get(post_src["creator"], ""),
                        "timestamp": int(dt.timestamp()),
                        "comments": self.expand_number(post_src["comments"]),
                        "urls": ",".join([("https://api.parler.com/l/" + link) for link in post_src["links"]]),
                        "hashtags": ",".join(post_src["hashtags"]),
                        "impressions": self.expand_number(post_src["impressions"]),
                        "reposts": self.expand_number(post_src["reposts"]),
                        "upvotes": self.expand_number(post_src["upvotes"]),
                        "permalink": post_src.get("shareLink", ""),
                        "reposted_by": reposted_by
                    }

                    if min_timestamp and dt.timestamp() < min_timestamp:
                        done = True
                        break

                    if max_timestamp and dt.timestamp() >= max_timestamp:
                        continue

                    num_posts += 1
                    yield post

                    if num_posts >= max_posts:
                        break

                self.dataset.update_status(
                    "Retrieved %i posts for query '%s' (%i/%i)" % (num_posts, query, num_query, len(queries)))

                # paginate, if needed
                if not done and num_posts < max_posts and not chunk_posts["last"]:
                    cursor = chunk_posts["next"]
                    time.sleep(1.5)
                else:
                    break

            time.sleep(1)

    def expand_number(self, num_str):
        """
        Expand '3.3k' to 3300, etc

        :param str num_str:  Number string
        :return int:  Expanded number
        """
        num_str = str(num_str)
        if "k" in num_str:
            return float(num_str.replace("k", "")) * 1000
        if "m" in num_str:
            return float(num_str.replace("m", "")) * 1000000
        if "b" in num_str:
            return float(num_str.replace("b", "")) * 1000000000
        else:
            return int(num_str)

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

        if not query.get("jst") or not query.get("mst"):
            raise QueryParametersException("You must provide the 'JST' and 'MST' values")

        # 500 is mostly arbitrary - may need tweaking
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

        # the dates need to make sense as a range to search within
        after, before = query.get("daterange")
        if before and after and before < after:
            raise QueryParametersException("Date range must start before it ends")

        query["min_date"], query["max_date"] = (after, before)

        # simple!
        return {
            "items": max_posts,
            "query": items,
            "min_date": query.get("min_date", None),
            "max_date": query.get("max_date", None),
            "jst": query.get("jst"),
            "mst": query.get("mst"),
            "scrape_echoes": bool(query.get("scrape_echoes", False))
        }

    def request_from_parler(self, session, method, url, headers=None, data=None):
        """
        Request something via the Parler API (or non-API)

        To avoid having to write the same error-checking everywhere, this takes
        care of retrying on failure, et cetera

        :param session:  Requests session
        :param str method: GET or POST
        :param str url:  URL to fetch
        :param dict header:  Headers to pass with the request
        :param dict data:  Data/params to send with the request

        :return:  Requests response
        """
        retries = 0
        response = None
        while retries < 3:
            try:
                if method.lower() == "post":
                    request = session.post(url, headers=headers, data=data)
                elif method.lower() == "get":
                    request = session.get(url, headers=headers, params=data)
                else:
                    raise NotImplemented()

                if request.status_code >= 500:
                    raise ConnectionError()

                return request

            except (ConnectionError, requests.RequestException) as e:
                retries += 1
                time.sleep(retries * 3)

            except json.JSONDecodeError as e:
                self.log.warning("Error decoding JSON: %s\n\n%s" % (e, request.text))

        if not response:
            self.log.warning("Failed Parler request to %s %i times, aborting" % (url, retries))
            raise RuntimeError()

        return response
