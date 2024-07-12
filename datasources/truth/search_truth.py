"""
Import scraped Truth Social data
"""
import datetime
import re

from backend.lib.search import Search


class SearchGab(Search):
    """
    Import scraped truth social data
    """
    type = "truthsocial-search"  # job ID
    category = "Search"  # category
    title = "Import scraped Truth Social data"  # title displayed in UI
    description = "Import Truth Social data collected with an external tool such as Zeeschuimer."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_from_extension = True
    fake = ""

    # not available as a processor for existing datasets
    accepts = [None]

    def get_items(self, query):
        """
        Run custom search

        Not available for Truth Social
        """
        raise NotImplementedError("Truth Social datasets can only be created by importing data from elsewhere")

    @staticmethod
    def map_item(post):
        """
        Parse Truth Social post

        :param post:  Data as received from Truth Social
        :return dict:  Mapped item
        """
        
        post_time = datetime.datetime.strptime(post["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
        media_length = 0
        if "media_attachments" in post:
            media_length = len(post["media_attachments"])

        if media_length > 0:
            mapped_item = {
                "id": post["id"],
                "created_at": post["created_at"],
                "body": post["content"],
                "url": post.get("url", None),
                "reblogs_count": post.get("reblogs_count", 0),
                "replies_count": post.get("replies_count", 0),
                
                "account_id": post["account"]["id"],
                "account_username": post["account"]["username"],
                "account_display_name": post["account"]["display_name"],
                "account_avatar": post["account"]["avatar"],
                "account_verified": post["account"]["verified"],
                "account_followers": post["account"]["followers_count"],
                "account_following": post["account"]["following_count"],

                "media_id": post["media_attachments"][0].get("id", None),
                "media_type": post["media_attachments"][0].get("type", None),
                "media_url": post["media_attachments"][0].get("url", None),
                "media_preview_url": post["media_attachments"][0].get("preview_url", None),

                #"group_id": post["group"].get("id", None),
                #"group_display_name": post["group"].get("display_name", None),
                #"group_avatar": post["group"].get("avatar", None),
                #"group_header": post["group"].get("header", None),
                #"group_members_count": post["group"].get("members_count", 0),

                "thread_id": post["id"],
                "timestamp": post_time.strftime("%Y-%m-%d %H:%M:%S")
            }        

        else:
            mapped_item = {
                "id": post["id"],
                "created_at": post["created_at"],
                "body": post["content"],
                "url": post.get("url", None),
                "reblogs_count": post.get("reblogs_count", 0),
                "replies_count": post.get("replies_count", 0),
                
                "account_id": post["account"]["id"],
                "account_username": post["account"]["username"],
                "account_display_name": post["account"]["display_name"],
                "account_avatar": post["account"]["avatar"],
                "account_verified": post["account"]["verified"],
                "account_followers": post["account"]["followers_count"],
                "account_following": post["account"]["following_count"],

                #"group_id": post["group"].get("id", None),
                #"group_display_name": post["group"].get("display_name", None),
                #"group_avatar": post["group"].get("avatar", None),
                #"group_header": post["group"].get("header", None),
                #"group_members_count": post["group"].get("members_count", 0),

                "thread_id": post["id"],
                "timestamp": post_time.strftime("%Y-%m-%d %H:%M:%S")
            }       
    
        return mapped_item
