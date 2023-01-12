"""
VK keyword search
"""
import datetime
from pathlib import Path

import vk_api

from backend.abstract.search import Search
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException
from common.lib.helpers import UserInput
import common.config_manager as config


class SearchVK(Search):
    """
    Get posts via the VK API
    """
    type = "vk-search"  # job ID
    title = "VK"
    extension = "ndjson"
    is_local = False    # Whether this datasource is locally scraped
    is_static = False   # Whether this datasource is still updated

    previous_request = 0
    flawless = True

    references = [
        "[VK API documentation](https://vk.com/dev/first_guide)",
        "[Python API wrapper](https://github.com/python273/vk_api)"
    ]

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        Get VK data source options

        :param parent_dataset:  Should always be None
        :param user:  User to provide options for
        :return dict:  Data source options
        """

        intro_text = ("This data source uses VK's [API](https://vk.com/dev/first_guide) and a python "
                      "[wrapper](https://github.com/python273/vk_api) to request information from VK using your "
                      "username and password.")

        options = {
            "intro-1": {
                "type": UserInput.OPTION_INFO,
                "help": intro_text
            },
            "query_type": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Query Type",
                "options": {
                    "newsfeed": "News Feed search",
                },
                "default": "newsfeed"
            },
            "intro-2": {
                "type": UserInput.OPTION_INFO,
                "help": "Your username and password will be deleted after your query is complete."
            },
            "username": {
                "type": UserInput.OPTION_TEXT,
                "sensitive": True,
                "cache": True,
                "help": "VK Username"
            },
            "password": {
                "type": UserInput.OPTION_TEXT,
                "sensitive": True,
                "cache": True,
                "help": "VK Password"
            },
            "intro-3": {
                "type": UserInput.OPTION_INFO,
                "help": "Enter the text to search for below."
            },
            "query": {
                "type": UserInput.OPTION_TEXT_LARGE,
                "help": "Query"
            },
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "help": "Max items to retrieve",
                "min": 0,
                "max": 1000,
                "default": 100
            },
            "divider-2": {
                "type": UserInput.OPTION_DIVIDER
            },
            "daterange-info": {
                "type": UserInput.OPTION_INFO,
                "help": "VK daterange defaults vary by type of query. For the News Feed, posts are returned starting "
                        "with the most recent and working backwards."
            },
            "daterange": {
                "type": UserInput.OPTION_DATERANGE,
                "help": "Date range"
            },
        }

        return options

    def get_items(self, query):
        """
        Use the VK API

        :param query:
        :return:
        """
        if self.parameters.get("username") is None or self.parameters.get("password") is None:
            self.dataset.update_status(
                "VK query failed or was interrupted; please create new query in order to provide username and password again.",
                is_final=True)
            return []

        vk_session = self.login(self.parameters.get("username"), self.parameters.get("password"))
        tools = vk_api.VkTools(vk_session)

        query_type = self.parameters.get("query_type")

        query = self.parameters.get("query")

        if query_type == "newsfeed":
            query_parameters = {"q": query}

            # Add start and end dates if proviced
            if self.parameters.get("min_date"):
                self.dataset.log(self.parameters.get("min_date"))
                # query_parameters['start_time'] = 0
            if self.parameters.get("max_date"):
                self.dataset.log(self.parameters.get("max_date"))
                # query_parameters['end_time'] = 0

            results_iterator = tools.get_all_slow_iter("newsfeed.search",
                                                        100,
                                                        query_parameters,
                                                        limit=self.parameters.get("amount"))

            num_items = 0
            for result in results_iterator:
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while fetching message data from the VK API")

                yield result

                num_items += 1
                self.dataset.update_status("Received %s of ~%s results from the VK API" % (num_items, self.parameters.get("amount")))
                self.dataset.update_progress(num_items / self.parameters.get("amount"))

    def login(self, username, password):
        """
        Login and authenticate user
        """
        vk_session = vk_api.VkApi(username,
                                  password,
                                  config_filename=Path(config.get("PATH_ROOT")).joinpath(config.get("PATH_SESSIONS"), username+"-vk_config.json"))
        vk_session.auth()

        return vk_session


    @staticmethod
    def validate_query(query, request, user):
        """
        Validate input for a dataset query on the VK data source.

        Will raise a QueryParametersException if invalid parameters are
        encountered. Parameters are additionally sanitised.

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """
        # Please provide something...
        if not query.get("query", None):
            raise QueryParametersException("Please provide a query.")

        # the dates need to make sense as a range to search within
        # but, on VK, you can also specify before *or* after only
        after, before = query.get("daterange")
        if before and after and before < after:
            raise QueryParametersException("Date range must start before it ends")

        # TODO: test username and password?

        # if we made it this far, the query can be executed
        params = {
            "query":  query.get("query"),
            "query_type": query.get("query_type"),
            "amount": query.get("amount"),
            "min_date": after,
            "max_date": before,
            "username": query.get("username"),
            "password": query.get("password"),
        }

        return params

    @staticmethod
    def map_item(vk_item):
        """
        Map a nested VK object to a flat dictionary

        :param vk_item:  VK object as originally returned by the VK API
        :return dict:  Dictionary in the format expected by 4CAT
        """
        vk_item_time = datetime.datetime.fromtimestamp(vk_item.get('date'))

        photos = []
        videos = []
        audio = []
        links = []
        docs = []

        for attachment in vk_item.get("attachments", []):
            attachment_type = attachment.get("type")
            attachment = attachment.get(attachment_type)
            if attachment_type == "photo":
                if attachment.get("sizes"):
                    photos.append(sorted(attachment.get("sizes"), key=lambda d: d['width'], reverse=True)[0].get('url'))
                else:
                    photos.append(str(attachment))
            elif attachment_type == "video":
                # TODO: can I get the actual URL? Does not seem like it...
                videos.append(f"https://vk.com/video{attachment.get('owner_id')}_{attachment.get('id')}")
            elif attachment_type == "audio":
                # TODO: Seem unable to create the URL with provided information...
                audio.append(f"{attachment.get('artist')} - {attachment.get('title')}")
            elif attachment_type == "link":
                links.append(attachment.get('url', str(attachment)))
            elif attachment_type == "doc":
                docs.append(attachment.get('url', str(attachment)))

        return {
            "id": vk_item.get("id"),
            "thread_id": "",
            "timestamp": vk_item_time.strftime("%Y-%m-%d %H:%M:%S"),
            "unix_timestamp": int(vk_item_time.timestamp()),
            "link": f"https://vk.com/wall{vk_item.get('owner_id')}_{vk_item.get('id')}",
            "post_type": vk_item.get("post_type"),
            "subject": "",
            "body": vk_item.get("text"),
            "author": vk_item.get("owner_id"),
            "source": vk_item.get("post_source", {}).get("type"),
            "views": vk_item.get("views", {}).get("count"),
            "likes": vk_item.get("likes", {}).get("count"),
            "comments": vk_item.get("comments", {}).get("count"),
            "edited": datetime.datetime.fromtimestamp(vk_item.get("edited")).strftime("%Y-%m-%d %H:%M:%S") if vk_item.get("edited", False) else False,
            "photos": ", ".join(photos),
            "videos": ", ".join(videos),
            "audio": ", ".join(audio),
            "links": ", ".join(links),
            "docs": ", ".join(docs),
        }
