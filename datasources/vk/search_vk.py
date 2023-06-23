"""
VK keyword search
"""
import datetime
from pathlib import Path

import vk_api

from backend.lib.search import Search
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException, ProcessorException
from common.lib.helpers import UserInput
from common.config_manager import config


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

    expanded_profile_fields = "id,screen_name,first_name,last_name,name,deactivated,is_closed,is_admin,sex,city,country,photo_200,photo_100,photo_50,followers_count,members_count"  # https://vk.com/dev/objects/user & https://vk.com/dev/objects/group

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

        self.dataset.update_status(f"Logging in to VK")
        try:
            vk_session = self.login(self.parameters.get("username"), self.parameters.get("password"))
        except vk_api.exceptions.AuthError as e:
            self.log.warning(f"VK Auth Issues: {e}")
            self.dataset.update_status(f"VK unable to authorize user: {e}", is_final=True)
            return []

        query_type = self.parameters.get("query_type")
        query = self.parameters.get("query")
        include_comments = self.parameters.get("include_comments", False)

        if query_type == "newsfeed":
            query_parameters = {"query": query,
                                "max_amount": self.parameters.get("amount")}

            # Add start and end dates if provided
            if self.parameters.get("min_date"):
                query_parameters['start_time'] = self.parameters.get("min_date")
            if self.parameters.get("max_date"):
                query_parameters['end_time'] = self.parameters.get("max_date")

            vk_helper = vk_session.get_api()

            # Collect Newsfeed results
            num_results = 0
            self.dataset.update_status(f"Submitting query...")
            for i, result_batch in enumerate(self.search_newsfeed(vk_helper, **query_parameters)):
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while fetching newsfeed data from the VK API")

                self.dataset.update_status(f"Processing results batch {i+1}")
                for result in result_batch:
                    result.update({'4cat_item_type': 'post'})
                    yield result
                    num_results += 1

                    if include_comments:
                        for comment in self.collect_all_comments(vk_helper, owner_id=result.get("owner_id"), post_id=result.get("id")):
                            comment.update({'4cat_item_type': 'comment'})
                            yield comment

                    self.dataset.update_status(f"Received {num_results} results of max {self.parameters.get('amount')} from the VK API")
                    self.dataset.update_progress(num_results / self.parameters.get('amount'))

    def login(self, username, password):
        """
        Login and authenticate user
        """
        vk_session = vk_api.VkApi(username,
                                  password,
                                  config_filename=Path(config.get("PATH_ROOT")).joinpath(config.get("PATH_SESSIONS"), username+"-vk_config.json"))
        vk_session.auth()

        return vk_session

    def search_newsfeed(self, vk_helper, query, max_amount, num_collected=0, start_time=None, end_time=None, **kwargs):
        """
        Collects all newsfeed posts

        :param Object vk_helper:    Authorized vk_api.VkApi
        :param str query:           String representing the search query
        :param int max_amount:      Max number of posts to collect
        :param int num_collected:   Number of previously collected results
        :param int start_time:      Timestamp for earliest post
        :param int end_time:        Timestamp for latest post
        :return generator:          Yields groups of posts
        """
        remaining = max_amount - num_collected
        parameters = {
            "q": query,
            "extended": 1,
            "count": remaining if remaining < 200 else 200,
            "fields": self.expanded_profile_fields,
        }
        if start_time:
            parameters["start_time"] = start_time
        if end_time:
            parameters["end_time"] = end_time

        response = vk_helper.newsfeed.search(**parameters)
        news_feed_results = response.get("items", [])
        num_collected = num_collected + len(news_feed_results)

        # Flesh out profiles and groups
        author_profiles = self.expand_profile_fields({"profiles": response.get("profiles", []), "groups": response.get("groups", [])})
        [result.update({"author_profile": author_profiles.get(result.get("from_id"), {})}) for result in news_feed_results]

        yield news_feed_results

        # Collect additional results
        if response.get("next_from") and num_collected < max_amount:
            parameters.update({"start_from": response.get("next_from")})
            for additional_results in self.search_newsfeed(vk_helper, query, max_amount, num_collected=num_collected, **parameters):
                yield additional_results

    def collect_all_comments(self, vk_helper, owner_id, post_id):
        """
        Collects all comments and replies to a VK post

        :param Object vk_helper:           Authorized vk_api.VkApi
        :param int owner_id:            Owner ID provided by post/comment/etc
        :param int post_id:             ID of post from which to collect comments
        :return generator:              Yields comments and replies
        """
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
                if reply.get("thread"):
                    self.log.warning("VK Datasource issue with replies: additional depth needs to be handled; contact 4CAT devs")
                    # TODO: this will need modification if reply threads gain depth

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
        if self.interrupted:
            raise ProcessorInterruptedException("Interrupted while fetching comments from the VK API")

        if post_id is None and comment_id is None:
            raise ProcessorException("Must provide either post_id or comment_id to collect comments from VK")

        parameters = {
            "owner_id": owner_id,
            "need_likes": 1,
            "preview_length": 0,
            "extended": 1,
            "count": 100,
            "thread_items_count": 10,
            "fields": self.expanded_profile_fields,
        }
        if post_id:
            parameters.update({"post_id": post_id})
        if comment_id:
            parameters.update({"comment_id": comment_id})
        if last_collected_id:
            parameters.update({"start_comment_id": last_collected_id})

        # Collect comments from VK
        try:
            response = vk_helper.wall.getComments(**parameters)
        except vk_api.exceptions.ApiError as e:
            self.dataset.log(f"Unable to collect comments for owner_id {owner_id} and {'post_id' if post_id is not None else 'comment_id'} {post_id if post_id is not None else comment_id}: {e}")
            return []
        comments = response.get("items", [])

        # Flesh out profiles and groups
        author_profiles = self.expand_profile_fields({"profiles": response.get("profiles", []), "groups": response.get("groups", [])})
        [comment.update({"author_profile": author_profiles.get(comment.get("from_id"), {})}) for comment in comments]
        # Also expand replies
        [reply.update({"author_profile": author_profiles.get(reply.get("from_id"), {})}) for replies in [comment.get("thread", {}).get("items", []) for comment in comments if comment.get("thread")] for reply in replies]

        # Check if there are potentially additional comments
        if response.get("count") > 100 and len(comments) == 100:
            # Update params with last collected comment
            parameters.update({"start_comment_id": comments[-1].get("id")})
            # Collect additional comments from VK and remove first comment (which is duplicate)
            comments += self.get_comments(vk_helper=vk_helper, **parameters)[1:]

        return comments

    @ staticmethod
    def expand_profile_fields(dict_of_profile_types):
        """
        Combine various VK profile and group author information for easy lookup. Add 4CAT_author_profile_type field to
        differentiate source of data later.
        """
        author_types = {}
        for profile_type, profiles in dict_of_profile_types.items():
            for profile in profiles:
                if "id" not in profile:
                    raise ProcessorException("Profile missing id field; VK data format incorrect/changed")
                elif profile.get("id") in author_types:
                    raise ProcessorException("Profile id duplicated across profile types; unable to combine profiles")
                profile.update({"4CAT_author_profile_type": profile_type})
                author_types[profile.get("id")] = profile
        return author_types

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

        # Process attachments
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

        # Use 4cat_item_type to populate different fields
        tread_id = ""
        in_reply_to_user = ""
        in_reply_to_comment_id = ""
        if vk_item.get("4cat_item_type") == "post":
            tread_id = vk_item.get("id")
        elif vk_item.get("4cat_item_type") == "comment":
            tread_id = vk_item.get("post_id")
            in_reply_to_user = vk_item.get("reply_to_user")
            in_reply_to_comment_id = vk_item.get("reply_to_comment")

        author_profile = vk_item.get("author_profile", {})
        profile_source = "user" if author_profile.get("4CAT_author_profile_type") == "profile" else "community" if author_profile.get("4CAT_author_profile_type") == "group" else "N/A"
        # Use source of author profile if "type" not present (e.g., in users profiles do not seem to have type)
        author_type = author_profile.get("type", profile_source)

        return {
            "id": vk_item.get("id"),
            "thread_id": tread_id,
            "timestamp": vk_item_time.strftime("%Y-%m-%d %H:%M:%S"),
            "unix_timestamp": int(vk_item_time.timestamp()),
            "link": f"https://vk.com/wall{vk_item.get('owner_id')}_{vk_item.get('id')}",
            "item_type": vk_item.get("4cat_item_type"),
            "body": vk_item.get("text"),
            "author_id": vk_item.get("from_id"),
            "author_type": author_type,
            "author_screen_name": author_profile.get("screen_name"),
            "author_name": author_profile.get("name", " ".join([author_profile.get("first_name", ""), author_profile.get("last_name", "")])),
            "author_sex": "F" if author_profile.get("sex") == 1 else "M" if author_profile.get("sex") == 2 else "Not Specified" if author_profile.get("sex") == 0 else author_profile.get("sex", "N/A"),
            "author_city": author_profile.get("city", {}).get("title", ""),
            "author_country": author_profile.get("country", {}).get("title", ""),
            "author_photo": author_profile.get("photo_200",
                                               author_profile.get("photo_100", author_profile.get("photo_50", ""))),
            "author_is_admin": True if author_profile.get("is_admin") == 1 else False if author_profile.get("is_admin") == 0 else author_profile.get("is_admin", "N/A"),
            "author_is_advertiser": True if author_profile.get("is_advertiser") == 1 else False if author_profile.get(
                "is_advertiser") == 0 else author_profile.get("is_advertiser", "N/A"),
            "author_deactivated": author_profile.get("is_deactivated", False),
            "author_privacy_is_closed": 'closed' if author_profile.get("is_closed") == 1 else 'open' if author_profile.get("is_closed") == 0 else 'private' if author_profile.get("is_closed") == 2 else author_profile.get("is_closed", "N/A"),
            "author_followers": author_profile.get("followers_count", author_profile.get("members_count", "N/A")),
            "in_reply_to_user": in_reply_to_user,
            "in_reply_to_comment_id": in_reply_to_comment_id,
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
            "subject": "",
        }
