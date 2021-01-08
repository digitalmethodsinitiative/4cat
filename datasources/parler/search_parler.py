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
from backend.lib.exceptions import QueryParametersException, ProcessorInterruptedException


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

    def get_posts_simple(self, query):
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
                    user_id = session.get("https://api.parler.com/v1/profile", params={"username": query}).json()["_id"]
                except KeyError:
                    # user does not exist or no results
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
                    chunk_posts = session.get(url, params=params)
                    print(chunk_posts.status_code)

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
                    if post.get("parent") and int(post.get("depth", 0)) == 1:
                        if not scrape_echoes:
                            continue

                        reposted_by = user_map.get(post["creator"])
                        post_src = ref_map[post.get("parent")]
                    else:
                        reposted_by = ""
                        post_src = post

                    dt = datetime.datetime.strptime(post["createdAt"], "%Y%m%d%H%M%S")
                    post = {
                        "id": post_src["_id"],
                        "thread_id": post_src["_id"],
                        "subject": "",
                        "body": post_src["body"],
                        "author": user_map.get(post_src["creator"], ""),
                        "timestamp": dt.timestamp(),
                        "comments": self.expand_number(post_src["comments"]),
                        "urls": ",".join([("https://api.parler.com/l/" + link) for link in post_src["links"]]),
                        "hashtags": ",".join(post_src["hashtags"]),
                        "impressions": self.expand_number(post_src["impressions"]),
                        "reposts": self.expand_number(post_src["reposts"]),
                        "upvotes": self.expand_number(post_src["upvotes"]),
                        "permalink": post_src.get("shareLink", ""),
                        "reposted_by": reposted_by
                    }

                    if min_timestamp > 0 and dt.timestamp() < min_timestamp:
                        done = True
                        break

                    if min_timestamp > 0 and dt.timestamp() >= max_timestamp:
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

        if query.get("min_date", None) and query.get("max_date", None):
            try:
                before = int(query.get("max_date", ""))
                after = int(query.get("min_date", ""))
            except ValueError:
                raise QueryParametersException("Please provide valid dates for the date range.")

            if before < after:
                raise QueryParametersException(
                    "Please provide a valid date range where the start is before the end of the range.")

            query["min_date"] = after
            query["max_date"] = before

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

    def get_search_mode(self, query):
        """
        Parler searches are always simple

        :return str:
        """
        return "simple"

    def get_posts_complex(self, query):
        """
        Complex post fetching is not used by the Parler datasource

        :param query:
        :return:
        """
        pass

    def fetch_posts(self, post_ids, where=None, replacements=None):
        """
        Posts are fetched via the Parler API for this datasource
        :param post_ids:
        :param where:
        :param replacements:
        :return:
        """
        pass

    def fetch_threads(self, thread_ids):
        """
        Thread filtering is not a toggle for Parler datasets

        :param thread_ids:
        :return:
        """
        pass

    def get_thread_sizes(self, thread_ids, min_length):
        """
        Thread filtering is not a toggle for Parler datasets

        :param tuple thread_ids:
        :param int min_length:
        results
        :return dict:
        """
        pass
