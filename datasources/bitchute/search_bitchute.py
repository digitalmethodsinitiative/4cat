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

    # scraping happens in one or the other method, so keep track of this internally
    max_items = 0

    def get_posts_simple(self, query):
        """
        Run custom search

        Fetches data from BitChute for either users or search queries
        """
        # ready our parameters
        parameters = self.dataset.get_parameters()
        self.max_items = parameters.get("items", 100)
        queries = [query.strip() for query in parameters.get("query", "").split(",")]
        num_query = 0
        detail = parameters.get("scope", "basic")
        query_type = parameters.get("item_type", "search")

        # bitchute uses a CSRF cookie that needs to be included on each request. The only way to obtain it is by
        # visiting the site, so do just that and extract the CSRF token from the page:
        session = requests.Session()
        session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:84.0) Gecko/20100101 Firefox/84.0"
        request = session.get("https://www.bitchute.com/search")
        csrftoken = BeautifulSoup(request.text, 'html.parser').findAll("input", {"name": "csrfmiddlewaretoken"})[0].get(
            "value")
        time.sleep(1)

        self.dataset.update_status("Querying BitChute")
        for query in queries:
            num_query += 1
            query = query.strip()

            if query_type == "search":
                return self.get_videos_query(session, query, csrftoken, detail)
            else:
                return self.get_videos_user(session, query, csrftoken, detail)

    def get_videos_user(self, session, user, csrftoken, detail):
        """
        Scrape videos for given BitChute user

        :param session:  HTTP Session to use
        :param str user:  Username to scrape videos for
        :param str csrftoken:  CSRF token to use for requests
        :param str detail:  Detail level to scrape, basic/detail/comments

        :return:  Video data dictionaries, as a generator
        """
        offset = 0
        num_items = 0
        base_url = "https://www.bitchute.com/channel/%s/" % user
        url = base_url + "extend/"

        container = session.get(base_url)
        container_soup = BeautifulSoup(container.text, 'html.parser')
        headers = {'Referer': base_url, 'Origin': "https://www.bitchute.com/"}

        while True:
            self.dataset.update_status("Retrieved %i items for query '%s'" % (num_items, user))

            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while scraping BitChute")

            post_data = {"csrfmiddlewaretoken": csrftoken, "name": "", "offset": str(offset)}

            try:
                request = session.post(url, data=post_data, headers=headers)
                if request.status_code != 200:
                    raise ConnectionError()
                response = request.json()
            except (json.JSONDecodeError, requests.RequestException, ConnectionError):
                self.dataset.update_status("Error while interacting with BitChute - try again later.", is_final=True)
                return

            soup = BeautifulSoup(response["html"], 'html.parser')
            videos = soup.select(".channel-videos-container")
            comments = []

            if len(videos) == 0 or num_items >= self.max_items:
                break

            for video_element in videos:
                if num_items >= self.max_items:
                    break
                else:
                    num_items += 1

                offset += 1

                link = video_element.select_one(".channel-videos-title a")
                video = {
                    "id": link["href"].split("/")[-2],
                    "thread_id": link["href"].split("/")[-2],
                    "subject": link.text,
                    "body": video_element.select_one(".channel-videos-text").encode_contents().decode("utf-8").strip(),
                    "author": container_soup.select_one(".details .name a").text,
                    "author_id": container_soup.select_one(".details .name a")["href"].split("/")[2],
                    "timestamp": int(
                        dateparser.parse(
                            video_element.select_one(".channel-videos-details.text-right.hidden-xs").text).timestamp()),
                    "url": "https://www.bitchute.com" + link["href"],
                    "views": video_element.select_one(".video-views").text.strip(),
                    "length": video_element.select_one(".video-duration").text.strip(),
                    "thumbnail": video_element.select_one(".channel-videos-image img")["src"],
                }

                if detail != "basic":
                    video, comments = self.append_details(video, detail)
                    if not video:
                        # unrecoverable error while scraping details
                        return

                yield video
                for comment in comments:
                    # these need to be yielded *after* the video because else the result file will have the comments
                    # before the video, which is weird
                    yield comment


    def get_videos_query(self, session, query, csrftoken, detail):
        """
        Scrape videos for given BitChute search query

        :param session:  HTTP Session to use
        :param str user:  Search query to scrape videos for
        :param str csrftoken:  CSRF token to use for requests
        :param str detail:  Detail level to scrape, basic/detail/comments

        :return:  Video data dictionaries, as a generator
        """
        page = 0
        num_items = 0
        while True:
            self.dataset.update_status("Retrieved %i items for query '%s'" % (num_items, query))

            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while scraping BitChute")

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
                self.dataset.update_status("Error while interacting with BitChute - try again later.", is_final=True)
                return

            if not response["success"] or response["count"] == 0 or num_items >= self.max_items:
                break

            comments = []
            for video_data in response["results"]:
                if num_items >= self.max_items:
                    break
                else:
                    num_items += 1

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
                    "thumbnail": video_data["images"]["thumbnail"]
                }

                if detail != "basic":
                    video, comments = self.append_details(video, detail)
                    if not video:
                        # unrecoverable error while scraping details
                        return

                yield video
                for comment in comments:
                    # these need to be yielded *after* the video because else the result file will have the comments
                    # before the video, which is weird
                    yield comment

            page += 1

    def append_details(self, video, detail):
        """
        Append extra metadata to video data

        Fetches the BitChute video detail page to scrape extra data for the given video.

        :param dict video:  Video details as scraped so far
        :param str detail:  Detail level. If 'comments', also scrape video comments.

        :return dict:  Tuple, first item: updated video data, second: list of comments
        """
        comments = []
        try:
            print(video["url"])
            # to get more details per video, we need to request the actual video detail page
            # start a new session, to not interfer with the CSRF token from the search session
            video_session = requests.session()

            video_page = video_session.get(video["url"])
            if "This video is unavailable as the contents have been deemed potentially illegal" in video_page.text:
                video = {
                    **video,
                    "category": "moderated-illegal",
                    "likes": "",
                    "dislikes": "",
                    "channel_subscribers": "",
                    "comments": "",
                    "parent_id": "",
                }
                return (video, [])

            soup = BeautifulSoup(video_page.text, 'html.parser')
            video_csfrtoken = soup.findAll("input", {"name": "csrfmiddlewaretoken"})[0].get("value")

            # we need *two more requests* to get the comment count and like/dislike counts
            # this seems to be because bitchute uses a third-party comment widget
            video_session.headers = {'Referer': video["url"], 'Origin': video["url"]}
            counts = video_session.post("https://www.bitchute.com/video/%s/counts/" % video["id"],
                                        data={"csrfmiddlewaretoken": video_csfrtoken})
            counts = counts.json()

            if detail == "comments":
                # if comments are also to be scraped, this is anothe request to make, which returns
                # a convenient JSON response with all the comments to the video
                # we need yet another token for this, which we can extract from a bit of inline
                # javascript on the page
                comment_script = None
                for line in video_page.text.split("\n"):
                    if line.strip().find("initComments") == 0:
                        comment_script = line.split("initComments(")[1]
                        break

                if not comment_script:
                    # no script to extract comments from, cannot load
                    comment_count = -1
                else:
                    # make the request
                    comment_count = 0
                    url = comment_script.split("'")[1]
                    comment_csrf = comment_script.split("'")[3]
                    comments_request = video_session.post(url + "/api/get_comments/",
                                                          data={"cf_auth": comment_csrf, "commentCount": 0})
                    comments_data = comments_request.json()

                    for comment in comments_data:
                        comment_count += 1
                        comments.append({
                            "id": comment["id"],
                            "thread_id": video["id"],
                            "subject": "",
                            "body": comment["content"],
                            "author": comment["fullname"],
                            "author_id": comment["creator"],
                            "timestamp": int(dateparser.parse(comment["created"]).timestamp()),
                            "url": "",
                            "views": "",
                            "length": "",
                            "thumbnail": url + comment["profile_picture_url"],
                            "likes": comment["upvote_count"],
                            "category": "comment",
                            "dislikes": "",
                            "channel_subscribers": "",
                            "comments": "",
                            "parent_id": comment.get("parent", "") if "parent" in comment else video["id"]
                        })

            else:
                # if we don't need the full comments, we still need another request to get the *amount*
                # of comments,
                comment_count = video_session.post(
                    "https://commentfreely.bitchute.com/api/get_comment_count/",
                    data={"csrfmiddlewaretoken": video_csfrtoken,
                          "cf_thread": "bc_" + video["id"]}).json()["commentCount"]

        except (json.JSONDecodeError, requests.RequestException, ConnectionError, IndexError):
            # we wrap this in one big try-catch because doing it for each request separarely is tedious
            # hm... maybe this should be in a helper function
            self.dataset.update_status("Error while interacting with BitChute - try again later.",
                                       is_final=True)
            return (None, None)

        # again, no structured info available for the publication date, but at least we can extract the
        # exact day it was uploaded
        try:
            published = dateparser.parse(
                soup.find(class_="video-publish-date").text.split("published at")[1].strip()[:1])
        except AttributeError:
            # publication date not on page?
            published = None

        # merge data
        video = {
            **video,
            "category": re.findall(r'<td><a href="/category/([^/]+)/"', video_page.text)[0],
            "likes": counts["like_count"],
            "dislikes": counts["dislike_count"],
            "channel_subscribers": counts["subscriber_count"],
            "comments": comment_count,
            "parent_id": "",
            "views": counts["view_count"]
        }

        if published:
            video["timestamp"] = int(published.timestamp())

        # may need to be increased? bitchute doesn't seem particularly strict
        time.sleep(0.5)
        return (video, comments)

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

        if query.get("search_scope", "") not in ("basic", "detail", "comments"):
            raise QueryParametersException("Invalid search scope: must be basic or detail")

        if query.get("search_type", "") not in ("user", "search"):
            raise QueryParametersException("Invalid search type: must be user or search")

        # 500 is mostly arbitrary - may need tweaking
        max_posts = 2500
        if query.get("max_posts", ""):
            try:
                max_posts = min(abs(int(query.get("max_posts"))), max_posts)
            except TypeError:
                raise QueryParametersException("Provide a valid number of videos to query.")

        # reformat queries to be a comma-separated list with no wrapping
        # whitespace
        items = query.get("query").replace("\n", ",")
        if len(items.split(",")) > 15:
            raise QueryParametersException("You cannot query more than 10 items at a time.")

        # simple!
        return {
            "items": max_posts,
            "query": items,
            "scope": query.get("search_scope"),
            "item_type": query.get("search_type")
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
