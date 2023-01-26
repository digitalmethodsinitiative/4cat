"""
VK keyword search
"""
import datetime
from pathlib import Path

import vk_api

from backend.abstract.search import Search
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException, ProcessorException
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
            "include_comments": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Include post comments",
                "default": False,
                "tooltip": ""
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
        include_comments = self.parameters.get("include_comments", False)

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

            if include_comments:
                vk_helper = vk_session.get_api()

            num_posts = 0
            for result in results_iterator:
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while fetching message data from the VK API")

                result.update({'4cat_item_type': 'post'})
                yield result
                num_posts += 1

                if include_comments:
                    for comment in self.collect_all_comments(vk_helper, owner_id=result.get("owner_id"), post_id=result.get("id")):
                        comment.update({'4cat_item_type': 'comment'})
                        yield comment

                self.dataset.update_status("Received %s of ~%s results from the VK API" % (num_posts, self.parameters.get("amount")))
                self.dataset.update_progress(num_posts / self.parameters.get("amount"))

    def login(self, username, password):
        """
        Login and authenticate user
        """
        vk_session = vk_api.VkApi(username,
                                  password,
                                  config_filename=Path(config.get("PATH_ROOT")).joinpath(config.get("PATH_SESSIONS"), username+"-vk_config.json"))
        vk_session.auth()

        return vk_session

    def collect_all_comments(self, vk_helper, owner_id, post_id):
        """
        Collects all comments and replies to a VK post

        :param Object vk_helper:           Authorized vk_api.VkApi
        :param int owner_id:            Owner ID provided by post/comment/etc
        :param int post_id:             ID of post from which to collect comments
        :return generator:              Yields comments and replies
        """
        # TODO: this will need modification if reply threads gain depth

        # Collect top level comments from post
        comments = self.get_comments(vk_helper, owner_id, post_id=post_id)

        # Extract replies and collect more if needed
        for comment in comments:
            yield comment

            reply_count = comment.get("thread", {}).get("count", 0)
            replies = comment.get("thread", {}).get("items", [])
            if reply_count > 10 and len(replies) == 10:
                # Collect additional replies
                replies += self.get_comments(vk_helper, owner_id, comment_id=comment.get("id"), last_collected_id=replies[-1].get("id"))[1:]

            for reply in replies:
                yield reply

    def get_comments(self, vk_helper, owner_id, post_id=None, comment_id=None, last_collected_id=None, **kwargs):
        """
        Collect comments from either a post or another comment (i.e., replies to another comment). Must provide either
        post_id or comment_id, but not both.

        More information can be found here:
        https://vk.com/dev/wall.getComments

        :param Object vk_helper:       Authorized vk_api.VkApi
        :param int owner_id:            Owner ID provided by post/comment/etc
        :param int post_id:             ID of post from which to collect comments
        :param int comment_id:          ID of comment from which to collect comments
        :param int last_collected_id:   ID of the last comment to collected; used as start to continue collecting comments
        :return list:                   List of comments
        """
        if post_id is None and comment_id is None:
            raise ProcessorException("Must provide either post_id or comment_id to collect comments from VK")

        parameters = {
            "owner_id": owner_id,
            "need_likes": 1,
            "preview_lenth": 0,
            "extended": 1,
            "count": 100,
            "thread_items_count": 10,
        }
        if post_id:
            parameters.update({"post_id": post_id})
        if comment_id:
            parameters.update({"comment_id": comment_id})
        if last_collected_id:
            parameters.update({"start_comment_id": last_collected_id})

        # Collect comments from VK
        self.dataset.log(f"DEBUG VK getComments params: {parameters}")
        try:
            response = vk_helper.wall.getComments(**parameters)
        except vk_api.exceptions.ApiError as e:
            self.dataset.log(f"Unable to collect comments for owner_id {owner_id} and {'post_id' if post_id is not None else 'comment_id'} {post_id if post_id is not None else comment_id}: {e}")
            return []
        comments = response.get("items", [])

        # Flesh out profiles
        profiles = {profile.get("id"): profile for profile in response.get("profiles", [])}
        [comment.update({"owner_profile": profiles.get(comment.get("from_id"), {})}) for comment in comments]

        # Check if there are potentially additional comments
        if response.get("count") > 100 and len(comments) == 100:
            # Update params with last collected comment
            parameters.update({"start_comment_id": comments[-1].get("id")})
            # Collect additional comments from VK and remove first comment (which is duplicate)
            comments += self.get_comments(vk_helper=vk_helper, **parameters)[1:]

        return comments

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
            "include_comments": query.get("include_comments"),
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
            "item_type": vk_item.get("4cat_item_type"),
            "post_type": vk_item.get("post_type"),
            "subject": "",
            "body": vk_item.get("text"),
            "author": vk_item.get("owner_id"),
            "source": vk_item.get("post_source", {}).get("type"),
            "views": vk_item.get("views", {}).get("count"),
            "likes": vk_item.get("likes", {}).get("count"),
            "post_comments": vk_item.get("comments", {}).get("count"),
            "edited": datetime.datetime.fromtimestamp(vk_item.get("edited")).strftime("%Y-%m-%d %H:%M:%S") if vk_item.get("edited", False) else False,
            "photos": ", ".join(photos),
            "videos": ", ".join(videos),
            "audio": ", ".join(audio),
            "links": ", ".join(links),
            "docs": ", ".join(docs),
        }
