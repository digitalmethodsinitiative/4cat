"""
Search LIHKG threads
"""
import requests
import datetime
import random
import time
import re

from bs4 import BeautifulSoup

from backend.abstract.search import Search
from common.lib.helpers import convert_to_int, strip_tags, UserInput
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException


class SearchLIHKG(Search):
    """
    Search LIHKG groups

    Defines methods that are used to query LIHKG data from the site directly
    """
    type = "lihkg-search"  # job ID
    category = "Search"  # category
    title = "LIHKG Search"  # title displayed in UI
    description = "Scrapes posts from LIHKG for a given search query"  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_local = False  # Whether this datasource is locally scraped
    is_static = False  # Whether this datasource is still updated

    # not available as a processor for existing datasets
    accepts = [None]

    max_workers = 1

    options = {
        "intro": {
            "type": UserInput.OPTION_INFO,
            "help": "This queries posts from [LIHKG](https://lihkg.com/), a web forum popular primarily in Hong Kong, "
                    "matching a given search query. For all matching threads, the posts in the thread are fetched. The "
                    "dataset then consists of all posts in those threads."
        },
        "query": {
            "type": UserInput.OPTION_TEXT,
            "help": "Search query",
            "tooltip": "Search query. This is anologous to the search feature on LIHKG itself."
        },
        "order": {
            "type": UserInput.OPTION_CHOICE,
            "options": {
                "score": "Thread score",
                "desc_create_time": "Most recently posted thread first",
                "desc_reply_time": "Most recently replied to thread first"
            },
            "help": "Thread order",
            "tooltip": "What order to return results in. Mostly relevant when capturing fewer than the total amount of "
                       "items."
        },
        "amount": {
            "type": UserInput.OPTION_TEXT,
            "coerce_type": int,
            "default": 500,
            "min": 0,
            "help": "Posts to capture",
            "tooltip": "Amount of posts to capture. Use '0' for unlimited."
        }
    }

    session = None

    def get_items(self, query):
        """
        Get LIHKG posts

        :param query:  Filtered query parameters
        :return:
        """
        query = self.parameters.get("query")
        order = self.parameters.get("order")
        amount = self.parameters.get("amount")
        page = 1
        num_threads = 0
        total_posts = 0
        errors = False

        # loop through thread search results for the given query
        while not amount or total_posts < amount:
            threads = self.get_response(
                f"https://lihkg.com/api_v2/thread/search?q={query}&page={page}&count=100&sort={order}&type=thread",
                headers={"Referer": "https://lihkg.com/category/1"})

            if not threads.status_code == 200:
                self.dataset.log(f"Could not fetch LIHKG results (status {threads.status_code}).")
                errors = True
                break

            try:
                threads = threads.json()
            except ValueError as e:
                self.dataset.log(f"Could not parse LIHKG results as JSON ({e})")
                errors = True
                break

            if not threads.get("success"):
                if threads.get("error_code") == 100:
                    # no more results
                    break
                else:
                    self.dataset.log(f"LIHKG results were valid JSON, but query was unsuccessful")
                    errors = True
                    break

            if not threads.get("response", {}).get("items"):
                self.dataset.log(f"LIHKG results were valid JSON, but no results")
                break

            if len(threads["response"]["items"]) == 0:
                # no (more) results
                break

            # then loop through the threads and fetch the posts therein
            for thread in threads["response"]["items"]:
                thread_page = 1
                num_threads += 1
                num_posts = 0

                while thread_page <= thread["total_page"] and (not amount or total_posts < amount):
                    posts = self.get_response(
                        f"https://lihkg.com/api_v2/thread/{thread['thread_id']}/page/{thread_page}?order=reply_time",
                        headers={"Referer": f"https://lihkg.com/thread/{thread['thread_id']}/page/{thread_page}"})
                    try:
                        posts = posts.json()
                    except ValueError:
                        self.dataset.log(f"Cannot parse posts for thread {thread['thread_id']}, stopping")
                        errors = True
                        break

                    if not posts.get("success"):
                        self.dataset.log(
                            f"Result was valid JSON, but posts query was unsuccessful for thread {thread['thread_id']}, stopping")
                        break

                    if len(posts["response"].get("item_data", [])) == 0:
                        self.dataset.log(f"No more posts for thread {thread['thread_id']}, stopping")
                        break

                    # each post is an object
                    # add the thread info to the object because that's not part
                    # of it by default
                    for post in posts["response"].get("item_data", []):
                        post["thread"] = thread
                        yield post
                        num_posts += 1
                        total_posts += 1
                        if amount and total_posts >= amount:
                            break

                    plural = "s" if num_posts != 1 else ""
                    self.dataset.update_status(f"Collected {num_posts} post{plural} for thread {num_threads} ({total_posts} post(s) total so far)")
                    thread_page += 1

            page += 1

        if errors:
            self.dataset.update_status(
                "LIHKG search finished, but not all results could be parsed. See dataset log for details.",
                is_final=True)

    def get_response(self, url, headers):
        """
        Fetch URL from LIHKG

        LIHKG is pretty easy to query from but does use rate limits. Rate
        limiting seems to be on a per-session basis. When a 429 is
        encountered, use exponential backoff (starting at 1 minute) and
        reset the session before continuing. This together seems enough to
        scrape in peace.

        :param str url:  LIHKG URL to query
        :param dict headers:  Headers to send with the request
        :return: requestes response object
        """
        retries = 0
        wait = 30

        while retries < 5:
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while querying LIHKG")

            if not self.session:
                self.session = requests.session()
                self.session.headers.update({
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:107.0) Gecko/20100101 Firefox/107.0",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                    "DNT": "1",
                })

                # get index page to acquire cookie, etc
                self.get_response("https://lihkg.com/", {})

            response = self.session.get(url, headers=headers)
            if response.status_code == 429:
                retries += 1
                wait *= 2
                resume_at_str = datetime.datetime.fromtimestamp(time.time() + wait).strftime("%c")
                self.dataset.update_status(f"Hit LIHKG rate limit - waiting until {resume_at_str} to continue.")
                time.sleep(wait)
                self.session = None
                continue
            break

        time.sleep(1 + random.random())
        return response

    def validate_query(query, request, user):
        """
        Validate input for a dataset query on the LIHKG data source.

        Just require a query.

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """
        filtered_query = {}
        if not query.get("query", "").strip():
            raise QueryParametersException("You need to provide a search query.")

        return {
            "query": query.get("query", "").strip(),
            "amount": query.get("amount"),
            "order": query.get("order")
        }

    @staticmethod
    def map_item(item):
        """
        Map LIHKG post object to csv-ready row

        :param dict item:  LIHKG post to map
        :return dict:  Flattened dictionary ready for JSON
        """
        is_op = item["post_id"] == item["thread"]["first_post_id"]  # is first post?

        return {
            "id": item["post_id"],
            "thread_id": item["thread_id"],
            "author": item["user_nickname"],
            "author_gender": item["user"]["gender"],
            "author_status": item["user"]["level_name"],
            "subject": item["thread"]["title"] if is_op else "",
            "is_first_post": "yes" if is_op else "no",
            "timestamp": datetime.datetime.utcfromtimestamp(item["reply_time"]).strftime("%Y-%m-%d %H:%M:%S"),
            "body": strip_tags(item["msg"]),
            "likes": item["like_count"],
            "dislikes": item["dislike_count"],
            "score": item["vote_score"],
            "quotes": item["no_of_quote"],
            "thread_category": item["thread"]["category"]["name"],
            "unix_timestamp": item["reply_time"]
        }
