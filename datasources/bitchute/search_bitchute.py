"""
Search Bitchute

Scrape Bitchute videos via the Bitchute web API
"""
import dateparser
import requests
import json
import time
import re

from bs4 import BeautifulSoup

from backend.abstract.search import Search
from backend.lib.exceptions import QueryParametersException, ProcessorInterruptedException


class SearchBitChute(Search):
    """
    BitChute scraper
    """
    type = "bitchute-search"  # job ID
    category = "Search"  # category
    title = "Search BitChute"  # title displayed in UI
    description = "Retrieve BitChute videos"  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    # not available as a processor for existing datasets
    accepts = [None]

    # let's not get rate limited
    max_workers = 1

    def get_posts_simple(self, query):
        """
        Run custom search

        Fetches data from BitChute
        """

        # ready our parameters
        parameters = self.dataset.get_parameters()
        max_items = parameters.get("items", 100)
        queries = [query.strip() for query in parameters.get("query", "").split(",")]
        num_query = 0
        detailed = parameters.get("scope") == "detail"

        # bitchute uses a CSRF cookie that needs to be included on each request. The only way to obtain it is by
        # visiting the site, so do just that and extract the CSRF token from the page:
        session = requests.Session()
        session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:84.0) Gecko/20100101 Firefox/84.0"
        request = session.get("https://www.bitchute.com/search")
        csrftoken = BeautifulSoup(request.text, 'html.parser').findAll("input", {"name": "csrfmiddlewaretoken"})[0].get(
            "value")
        time.sleep(1)

        for query in queries:
            num_query += 1
            query = query.strip()

            page = 0
            num_results = 0
            while True:
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while scraping Parler")

                # prepare the request - the CSRF param *must* be the first or the request will fail
                post_data = {"csrfmiddlewaretoken": csrftoken, "query": query, "kind": "video", "duration": "",
                             "sort": "", "page": str(page)}
                headers = {'Referer': "https://www.bitchute.com/search", 'Origin': "https://www.bitchute.com/search"}
                try:
                    request = session.post("https://www.bitchute.com/api/search/list/", data=post_data, headers=headers)
                    if request.status_code != 200:
                        raise ConnectionError()
                    response = request.json()
                except (json.JSONDecodeError, requests.RequestException, ConnectionError):
                    self.dataset.update_status("Error while interacting with BitChute - try again later.",
                                               is_final=True)
                    return

                if response["count"] == 0 or num_results >= max_items:
                    break

                for video_data in response["results"]:
                    # this is only included as '5 months ago' and so forth, not exact date
                    # so use dateparser to at least approximate the date
                    dt = dateparser.parse(video_data["published"])

                    video = {
                        "id": video_data["id"],
                        "thread_id": video_data["id"],
                        "subject": video_data["name"],
                        "body": video_data["description"],
                        "author": video_data["channel_name"],
                        "author_id": video_data["channel_path"].split("/")[2],
                        "timestamp": int(dt.timestamp()),
                        "url": "https://www.bitchute.com" + video_data["path"],
                        "views": video_data["views"],
                        "length": video_data["duration"],
                        "thumbnail": video_data["images"]["thumbnail"],
                        "sensitivity": video_data["sensitivity"]
                    }

                    if detailed:
                        # to get more details per video, we need to request the actual video detail page
                        # start a new session, to not interfer with the CSRF token from the search session
                        video_session = requests.session()

                        try:
                            video_page = video_session.get(video["url"])
                            soup = BeautifulSoup(video_page.text, 'html.parser')
                            video_csfrtoken = soup.findAll("input", {"name": "csrfmiddlewaretoken"})[0].get("value")

                            # we need *two more requests* to get the comment count and like/dislike counts
                            # this seems to be because bitchute uses a third-party comment widget
                            video_session.headers = {'Referer': video["url"], 'Origin': video["url"]}
                            counts = video_session.post("https://www.bitchute.com/video/%s/counts/" % video["id"],
                                                        data={"csrfmiddlewaretoken": video_csfrtoken}).json()
                            comment_count = video_session.post(
                                "https://commentfreely.bitchute.com/api/get_comment_count/",
                                data={"csrfmiddlewaretoken": video_csfrtoken, "cf_thread": "bc_" + video["id"]}).json()

                        except (json.JSONDecodeError, requests.RequestException, ConnectionError, IndexError):
                            self.dataset.update_status("Error while interacting with BitChute - try again later.",
                                                       is_final=True)
                            return

                        # again, no structured info available for the publication date, but at least we can extract the
                        # exact day it was uploaded
                        published = dateparser.parse(
                            soup.find(class_="video-publish-date").text.split("published at")[1].strip()[:1])

                        # merge data
                        video = {
                            **video,
                            "category": re.findall(r'<a href="/category/([^/]+)/"', video_page.text)[0],
                            "likes": counts["like_count"],
                            "dislikes": counts["dislike_count"],
                            "channel_subscribers": counts["subscriber_count"],
                            "comments": comment_count["commentCount"]
                        }

                        if published:
                            video["timestamp"] = int(published.timestamp())

                        # may need to be increased? bitchute doesn't seem particularly strict
                        time.sleep(0.5)

                    num_results += 1
                    yield video

                page += 1
                self.dataset.update_status(
                    "Retrieved %i videos for query '%s' (%i/%i)" % (num_results, query, num_query, len(queries)))

    def validate_query(query, request, user):
        """
        Validate BitChute query input

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """
        # no query 4 u
        if not query.get("query", "").strip():
            raise QueryParametersException("You must provide a search query.")

        if query.get("search_scope", "") not in ("basic", "detail"):
            raise QueryParametersException("Invalid search scope: must be basic or detail")

        # 500 is mostly arbitrary - may need tweaking
        max_posts = 2500
        if query.get("max_posts", ""):
            try:
                max_posts = min(abs(int(query.get("max_posts"))), max_posts)
            except TypeError:
                raise QueryParametersException("Provide a valid number of videos to query.")

        # reformat queries to be a comma-separated list with no wrapping
        # whitespace
        whitespace = re.compile(r"\s+")
        items = whitespace.sub("", query.get("query").replace("\n", ","))
        if len(items.split(",")) > 10:
            raise QueryParametersException("You cannot query more than 10 items at a time.")

        # simple!
        return {
            "items": max_posts,
            "query": items,
            "scope": query.get("search_scope")
        }

    def get_search_mode(self, query):
        """
        BitChute searches are always simple

        :return str:
        """
        return "simple"

    def get_posts_complex(self, query):
        """
        Complex post fetching is not used by the BitChute datasource

        :param query:
        :return:
        """
        pass

    def fetch_posts(self, post_ids, where=None, replacements=None):
        """
        Posts are fetched via the BitChute API for this datasource
        :param post_ids:
        :param where:
        :param replacements:
        :return:
        """
        pass

    def fetch_threads(self, thread_ids):
        """
        Thread filtering is not a toggle for BitChute datasets

        :param thread_ids:
        :return:
        """
        pass

    def get_thread_sizes(self, thread_ids, min_length):
        """
        Thread filtering is not a toggle for BitChute datasets

        :param tuple thread_ids:
        :param int min_length:
        results
        :return dict:
        """
        pass
