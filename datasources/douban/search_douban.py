"""
Search Douban groups
"""
import requests
import datetime
import time
import re

from bs4 import BeautifulSoup

from backend.abstract.search import Search
from common.lib.helpers import convert_to_int, strip_tags, UserInput
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException


class SearchDouban(Search):
    """
    Search Douban groups

    Defines methods that are used to query Douban data from the site directly
    """
    type = "douban-search"  # job ID
    category = "Search"  # category
    title = "Douban Search"  # title displayed in UI
    description = "Scrapes group posts from Douban for a given set of groups"  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    # not available as a processor for existing datasets
    accepts = [None]

    max_workers = 1

    options = {
        "intro": {
            "type": UserInput.OPTION_INFO,
            "help": "You can enter the groups to scrape as group IDs (e.g. `687802`) or URLs (e.g. "
                    "`https://www.douban.com/group/687802/`. Separate multiple groups with commas or new lines. If "
                    "you enter more than 25 groups, only the first 25 will be scraped."
        },
        "groups": {
            "type": UserInput.OPTION_TEXT_LARGE,
            "help": "Groups",
            "tooltip": "Enter group IDs or URLs, separate with commas or new lines"
        },
        "divider": {
            "type": UserInput.OPTION_DIVIDER
        },
        "amount": {
            "type": UserInput.OPTION_TEXT,
            "help": "Threads per group",
            "min": 1,
            "max": 200,
            "default": 10
        },
        "strip": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Strip HTML?",
            "default": True
        },
        "divider-2": {
            "type": UserInput.OPTION_DIVIDER
        },
        "daterange-info": {
            "type": UserInput.OPTION_INFO,
            "help": "Note that Douban severely limits the retrieval of older content. Therefore this data source "
                    "can only scrape the most recent topics in a given group. You can optionally limit the scraped "
                    "topics to a given date range, but note that typically only the 500 or so most recent topics in a "
                    "group will be available for scraping."
        },
        "daterange": {
            "type": UserInput.OPTION_DATERANGE,
            "help": "Last post between"
        }
    }

    def get_items(self, query):
        """
        Get Douban posts

        In the case of Douban, there is no need for multiple pathways, so we
        can route it all to the one post query method. Will scrape posts from the
        most recent topics for a given list of groups. Douban prevents scraping
        old content, so this is mostly useful to get a sense of what a given
        group is talking about at the moment.

        :param query:  Filtered query parameters
        :return:
        """
        groups = query["groups"].split(",")
        max_topics = min(convert_to_int(query["amount"], 100), 500)
        start = query["min_date"]
        end = query["max_date"]
        strip = bool(query["strip"])
        topics_processed = 0
        posts_processed = 0

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:84.0) Gecko/20100101 Firefox/84.0"}

        for group in groups:
            # get URL for group index
            group = str(group)
            group_url = "https://www.douban.com/group/%s/discussion?start=" % group

            offset = 0
            while True:
                # get list of topics in group, for the given offset
                fetch_url = group_url + str(offset)
                request = self.get_douban_url(fetch_url, headers=headers)

                # this would usually mean the group doesn't exist, or we hit some rate limit
                if request.status_code != 200:
                    self.dataset.update_status(
                        "Got response code %i for group %s. Continuing with next group..." % (request.status_code, group))
                    break

                self.dataset.update_status("Scraping group %s...")

                # parse the HTML and get links to individual topics, as well as group name
                overview_page = BeautifulSoup(request.text, 'html.parser')
                group_name = overview_page.select_one(".group-item .title a").text

                for topic in overview_page.select("table.olt tr:not(.th)"):
                    if self.interrupted:
                        raise ProcessorInterruptedException("Interrupted while scraping Douban topics")

                    if topics_processed >= max_topics:
                        break

                    # get topic URL, and whether it is an 'elite' topic
                    topic_url = topic.find("a").get("href")
                    topic_is_elite = "yes" if bool(topic.select_one(".elite_topic_lable")) else "no"
                    topic_id = topic_url.split("/topic/").pop().split("/")[0]
                    topic_updated = int(
                        datetime.datetime.strptime(topic.select_one(".time").text, "%m-%d %H:%M").timestamp())

                    # if a date range is given, ignore topics outside of it
                    if start and topic_updated < start:
                        continue

                    if end and topic_updated > end:
                        break

                    self.dataset.update_status("%i posts scraped. Scraping topics %i-%i from group %s" % (
                    posts_processed, offset, min(max_topics, offset + 50), group_name))

                    # request topic page - fortunately all comments are on a single page
                    topic_request = self.get_douban_url(topic_url, headers=headers)
                    time.sleep(5)  # don't hit rate limits
                    topic_page = BeautifulSoup(topic_request.text, 'html.parser')
                    topic = topic_page.select_one("#topic-content")

                    topics_processed += 1

                    # include original post as the first item
                    try:
                        first_post = {
                            "id": topic_id,
                            "group_id": group,
                            "thread_id": topic_id,
                            "group_name": group_name,
                            "subject": topic_page.select_one("h1").text.strip(),
                            "body": topic_page.select_one(".topic-richtext").decode_contents(formatter="html").strip(),
                            "author": topic.select_one(".user-face img").get("alt"),
                            "author_id": topic.select_one(".user-face a").get("href").split("/people/").pop().split("/")[0],
                            "author_avatar": topic.select_one(".user-face img").get("src").replace("/u", "/ul"),
                            "timestamp": int(datetime.datetime.strptime(topic.select_one(".create-time").text,
                                                                        "%Y-%m-%d %H:%M:%S").timestamp()),
                            "likes": 0,
                            "is_highlighted": "no",
                            "is_reply": "no",
                            "is_topic_elite": topic_is_elite,
                            "image_urls": ",".join([img.get("src") for img in topic.select(".topic-richtext img")])
                        }
                    except (AttributeError, ValueError):
                        self.dataset.log("Unexpected data format when parsing topic %s/%s, skipping" % (group_name, topic_id))
                        continue

                    if strip:
                        first_post["body"] = strip_tags(first_post["body"])

                    posts_processed += 1
                    yield first_post

                    # now loop through all comments on the page
                    for comment in topic_page.select("ul#comments > li"):
                        comment_data = {
                            "id": comment.get("data-cid"),
                            "group_id": group,
                            "thread_id": topic_id,
                            "group_name": group_name,
                            "subject": "",
                            "body": comment.select_one(".reply-content").decode_contents(formatter="html").strip(),
                            "author": comment.select_one(".user-face img").get("alt"),
                            "author_id":
                                comment.select_one(".user-face a").get("href").split("/people/").pop().split("/")[0],
                            "author_avatar": comment.select_one(".user-face img").get("src").replace("/u", "/ul"),
                            "timestamp": int(datetime.datetime.strptime(comment.select_one(".pubtime").text,
                                                                        "%Y-%m-%d %H:%M:%S").timestamp()),
                            "likes": convert_to_int(
                                re.sub(r"[^0-9]", "", comment.select_one(".comment-vote.lnk-fav").text), 0),
                            "is_highlighted": "yes" if comment.get("data-cid") in [hl.get("data-cid") for hl in
                                                                                   comment.select(
                                                                                       "ul#popular-comments li")] else "no",
                            "is_reply": "yes" if comment.select_one(".reply-quote-content") else "no",
                            "is_topic_elite": topic_is_elite,
                            "image_urls": ",".join([img.get("src") for img in comment.select(".reply-content img")])
                        }

                        if strip:
                            comment_data["body"] = strip_tags(comment_data["body"])

                        posts_processed += 1
                        yield comment_data

                if offset < max_topics - 50:
                    offset += 50
                else:
                    break

    def get_douban_url(self, url, **kwargs):
        """
        Get Douban page with requests

        Abstracted away like this so we can easily implement measures to
        circumvent rate limiting later.

        :param str url:  URL to request
        :return:  Response object
        """
        if url[0:2] == "//":
            url = "https:" + url
        elif url[0] == "/":
            url = "https://douban.com" + url

        return requests.get(url, **kwargs)

    def validate_query(query, request, user):
        """
        Validate input for a dataset query on the Douban data source.

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """
        filtered_query = {}

        # the dates need to make sense as a range to search within
        after, before = query.get("daterange")
        if before and after and before < after:
            raise QueryParametersException("Date range must start before it ends")

        filtered_query["min_date"], filtered_query["max_date"] = (after, before)

        # normalize groups to just their IDs, even if a URL was provided, and
        # limit to 25
        groups = [group.split("/group/").pop().split("/")[0].strip() for group in
                  query["groups"].replace("\n", ",").split(",")]
        groups = [group for group in groups if group][:25]
        if not any(groups):
            raise QueryParametersException("No valid groups were provided.")

        filtered_query["groups"] = ",".join(groups)

        # max amount of topics is 200 because after that Douban starts throwing 429s
        filtered_query["amount"] = max(min(convert_to_int(query["amount"], 10), 200), 1)

        # strip HTML from posts?
        filtered_query["strip"] = bool(query.get("strip", False))

        return filtered_query
