"""
Search Bitchute

Scrape Bitchute videos via the Bitchute web API
"""
import dateparser
import requests
import json
import time
import re

from itertools import chain
from bs4 import BeautifulSoup

from common.lib.helpers import UserInput, strip_tags
from backend.abstract.search import Search
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException


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

    options = {
        "intro": {
            "type": UserInput.OPTION_INFO,
            "help": "Videos are scraped in the order they are returned by [BitChute](https://bitchute.com)'s search "
                    "function.\n\nYou can scrape results for up to **fifteen** items at a time. Separate the items "
                    "with commas or blank lines. When searching for usernames, there is no need to include @ in front."
        },
        "search_type": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Search by",
            "options": {
                "search": "Search query",
                "user": "Username",
                "url": "Video URL or ID"
            },
            "default": "search"
        },
        "query": {
            "type": UserInput.OPTION_TEXT_LARGE,
            "help": "Query"
        },
        "max_posts": {
            "type": UserInput.OPTION_TEXT,
            "help": "Videos per item",
            "min": 0,
            "max": 2500,
            "default": 10
        },
        "divider": {
            "type": UserInput.OPTION_DIVIDER
        },
        "enrichment-info": {
            "type": UserInput.OPTION_INFO,
            "help": "You can optionally scrape more details - exact publication date, likes, dislikes, category, "
                    "comment count and channel subscriber count - for each video. Note that this takes a couple of "
                    "seconds per video (which can add up!). Consider doing a basic query first and then repeating it "
                    "with more details only if necessary."
        },
        "search_scope": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Search scope",
            "options": {
                "basic": "Basic",
                "detail": "Detailed",
                "comments": "Detailed, also scrape video comments"
            },
            "default": "basic"
        }

    }

    def get_items(self, query):
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
        time.sleep(0.25)

        self.dataset.update_status("Querying BitChute")
        results = []
        for query in queries:
            num_query += 1
            query = query.strip()

            if query_type == "search":
                results.append(self.get_videos_query(session, query, csrftoken, detail))
            elif query_type == "url":
                if "/video/" in query:
                    query = query.split("/video/")[1].split("/")[0]
                    # else assume bare ID

                self.dataset.update_status("Getting details for video '%s' (%i/%i)" % (query, num_query, len(queries)))
                results.append(self.get_videos_id(session, query, csrftoken, detail))
            else:
                results.append(self.get_videos_user(session, query, csrftoken, detail))

        return chain(*results)

    def get_videos_id(self, session, video_id, csrftoken, detail):
        dummy_video = {
            "id": video_id,
            "thread_id": video_id,
            "subject": "",
            "body": "",
            "author": "",
            "author_id": "",
            "timestamp": None,
            "url": "https://www.bitchute.com/video/" + video_id + "/",
            "views": None,
            "length": None,
            "thumbnail_image": None,

        }

        # we can't use the BitChute search, so do one request per URL, and
        # get details for 'free'
        if detail == "basic":
            detail = "detail"

        video, comments = self.append_details(dummy_video, detail)
        if not video:
            # unrecoverable error while scraping details
            return

        yield video
        for comment in comments:
            # these need to be yielded *after* the video because else the result file will have the comments
            # before the video, which is weird
            yield comment

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
                self.dataset.log("Fetching data for BitChute video %s" % url)
                request = session.post(url, data=post_data, headers=headers)
                if request.status_code != 200:
                    raise ConnectionError()
                response = request.json()
            except (json.JSONDecodeError, requests.RequestException, ConnectionError) as e:
                self.dataset.update_status("Error while interacting with BitChute (%s) - try again later." % e, is_final=True)
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
                    "body": strip_tags(video_element.select_one(".channel-videos-text").text),
                    "author": container_soup.select_one(".details .name a").text,
                    "author_id": container_soup.select_one(".details .name a")["href"].split("/")[2],
                    "timestamp": int(
                        dateparser.parse(
                            video_element.select_one(".channel-videos-details.text-right.hidden-xs").text).timestamp()),
                    "url": "https://www.bitchute.com" + link["href"],
                    "views": video_element.select_one(".video-views").text.strip(),
                    "length": video_element.select_one(".video-duration").text.strip(),
                    "thumbnail_image": video_element.select_one(".channel-videos-image img")["src"],
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
            response = self.request_from_bitchute(session, "POST", "https://www.bitchute.com/api/search/list/", headers, post_data)

            if not response["success"] or response["count"] == 0 or num_items >= self.max_items:
                break

            comments = []
            for video_data in response["results"]:
                if num_items >= self.max_items:
                    break
                else:
                    num_items += 1

                # note: deleted videos will have a published date of 'None'. To
                # avoid crashing the backend the easiest way is to set it to something
                # that is obviously not a valid date in this context.
                if video_data["published"] is None:
                    video_data["published"] = "1970-01-01"
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
                    "thumbnail_image": video_data["images"]["thumbnail"]
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

        video = {
            **video,
            "likes": "",
            "dislikes": "",
            "channel_subscribers": "",
            "comments": "",
            "hashtags": "",
            "parent_id": "",
            "video_url": ""
        }

        try:
            # to get more details per video, we need to request the actual video detail page
            # start a new session, to not interfere with the CSRF token from the search session
            video_session = requests.session()
            video_page = video_session.get(video["url"])

            if "<h1 class=\"page-title\">Video Restricted</h1>" in video_page.text or \
                    "<h1 class=\"page-title\">Video Blocked</h1>" in video_page.text or \
                    "<h1 class=\"page-title\">Channel Blocked</h1>" in video_page.text or \
                    "<h1 class=\"page-title\">Channel Restricted</h1>" in video_page.text:
                if "This video is unavailable as the contents have been deemed potentially illegal" in video_page.text:
                    video["category"] = "moderated-illegal"
                    return (video, [])

                elif "Viewing of this video is restricted, as it has been marked as Not Safe For Life" in video_page.text:
                    video["category"] = "moderated-nsfl"
                    return (video, [])

                elif "Contains Incitement to Hatred" in video_page.text:
                    video["category"] = "moderated-incitement"
                    return (video, [])

                elif "Platform Misuse" in video_page.text:
                    video["category"] = "moderated-misuse"
                    return (video, [])

                elif "Terrorism &amp; Violent Extremism" in video_page.text:
                    video["category"] = "moderated-terrorism-extremism"
                    return (video, [])

                else:
                    video["category"] = "moderated-other"
                    self.log.warning("Unknown moderated reason for BitChute video %s" % video["id"])
                    return (video, [])

            elif "<iframe class=\"rumble\"" in video_page.text:
                # some videos are actually embeds from rumble?
                # these are iframes, so at the moment we cannot simply extract
                # their info from the page, so we skip them. In the future we
                # could add an extra request to get the relevant info, but so
                # far the only examples I've seen are actually 'video not found'
                video = {
                    **video,
                    "category": "error-embed-from-rumble"
                }
                return (video, [])

            elif video_page.status_code != 200:
                video = {
                    **video,
                    "category": "error-%i" % video_page.status_code
                }
                return (video, [])

            soup = BeautifulSoup(video_page.text, 'html.parser')
            video_csfrtoken = soup.findAll("input", {"name": "csrfmiddlewaretoken"})[0].get("value")

            video["video_url"] = soup.select_one("video#player source").get("src")
            video["thumbnail_image"] = soup.select_one("video#player").get("poster")
            video["subject"] = soup.select_one("h1#video-title").text
            video["author"] = soup.select_one("div.channel-banner p.name a").text
            video["author_id"] = soup.select_one("div.channel-banner p.name a").get("href").split("/")[2]
            video["body"] = soup.select_one("div#video-description").encode_contents().decode("utf-8").strip()

            # we need *two more requests* to get the comment count and like/dislike counts
            # this seems to be because bitchute uses a third-party comment widget
            video_session.headers = {'Referer': video["url"], 'Origin': video["url"]}
            counts = self.request_from_bitchute(video_session, "POST", "https://www.bitchute.com/video/%s/counts/" % video["id"], data={"csrfmiddlewaretoken": video_csfrtoken})

            if detail == "comments":
                # if comments are also to be scraped, this is anothe request to make, which returns
                # a convenient JSON response with all the comments to the video
                # we need yet another token for this, which we can extract from a bit of inline
                # javascript on the page
                comment_script = None
                for line in video_page.text.split("\n"):
                    if "initComments(" in line:
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
                    comments_data = self.request_from_bitchute(video_session, "POST", url + "/api/get_comments/", data={"cf_auth": comment_csrf, "commentCount": 0})

                    for comment in comments_data:
                        comment_count += 1

                        if comment.get("profile_picture_url", None):
                            thumbnail_image = url + comment.get("profile_picture_url")
                        else:
                            thumbnail_image = ""

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
                            "hashtags": "",
                            "thumbnail_image": thumbnail_image,
                            "likes": comment["upvote_count"],
                            "category": "comment",
                            "dislikes": "",
                            "channel_subscribers": "",
                            "comments": "",
                            "parent_id": comment.get("parent", "") if "parent" in comment else video["id"],
                        })

            else:
                # if we don't need the full comments, we still need another request to get the *amount*
                # of comments,
                comment_count = self.request_from_bitchute(video_session, "POST",
                    "https://commentfreely.bitchute.com/api/get_comment_count/",
                    data={"csrfmiddlewaretoken": video_csfrtoken,
                          "cf_thread": "bc_" + video["id"]})["commentCount"]

        except RuntimeError as e:
            # we wrap this in one big try-catch because doing it for each request separarely is tedious
            # hm... maybe this should be in a helper function
            self.dataset.update_status("Error while interacting with BitChute (%s) - try again later." % e,
                                       is_final=True)
            return (None, None)

        # again, no structured info available for the publication date, but at least we can extract the
        # exact day it was uploaded
        try:
            published = dateparser.parse(
                soup.find(class_="video-publish-date").text.split("published at")[1].strip()[:-1])
        except AttributeError as e:
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
            "hashtags": ",".join([tag.text for tag in soup.select("#video-hashtags li a")]),
            "views": counts["view_count"]
        }

        if published:
            video["timestamp"] = int(published.timestamp())

        # may need to be increased? bitchute doesn't seem particularly strict
        time.sleep(0.25)
        return (video, comments)

    def request_from_bitchute(self, session, method, url, headers=None, data=None):
        """
        Request something via the BitChute API (or non-API)

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

                response = request.json()
                return response

            except (ConnectionResetError, requests.RequestException) as e:
                retries += 1
                time.sleep(retries * 2)

            except json.JSONDecodeError as e:
                self.log.warning("Error decoding JSON: %s\n\n%s" % (e, request.text))

        if not response:
            self.log.warning("Failed BitChute request to %s %i times, aborting" % (url, retries))
            raise RuntimeError()

        return response


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

        # reformat queries to be a comma-separated list with no wrapping
        # whitespace
        items = query.get("query").replace("\n", ",")
        if len(items.split(",")) > 15 and query.get("search_type") != "url":
            raise QueryParametersException("You cannot query more than 15 items at a time.")

        # simple!
        return {
            "items": query.get("max_posts"),
            "query": items,
            "scope": query.get("search_scope"),
            "item_type": query.get("search_type")
        }
