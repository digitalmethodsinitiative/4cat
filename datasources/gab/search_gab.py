"""
Import scraped Gab data

It's prohibitively difficult to scrape data from Gab within 4CAT itself
due to its aggressive rate limiting and login wall. Instead, import data
collected elsewhere.
"""
import datetime
import re

from backend.lib.search import Search


class SearchGab(Search):
    """
    Import scraped gab data
    """
    type = "gab-search"  # job ID
    category = "Search"  # category
    title = "Import scraped Gab data"  # title displayed in UI
    description = "Import Gab data collected with an external tool such as Zeeschuimer."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_from_extension = True
    fake = ""

    # not available as a processor for existing datasets
    accepts = [None]

    def get_items(self, query):
        """
        Run custom search

        Not available for Gab
        """
        raise NotImplementedError("Gab datasets can only be created by importing data from elsewhere")

    @staticmethod
    def map_item(post):
        """
        Parse Gab post

        :param node:  Data as received from Gab
        :return dict:  Mapped item
        """

        post_time = datetime.datetime.strptime(post["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ")

        mapped_item = {
            "id": post["id"],
            "created_at": post["created_at"],
            "body" : post["content"],
            "url": post["url"],
            "reaction_count": post["reaction_count"],
            "reposts_count": post["reposts_count"],
            "replies_count": post["replies_count"],
            "group_id": post["group"]["title"],
            "group_description": post["group"]["description"],
            "group_member_count": post["group"]["member_count"],
            "group_is_private": post["group"]["is_private"],
            "group_url": post["group"]["url"],
            "group_created_at": post["group"]["created_at"],
            "account_id": post["account"]["id"],
            "account_username": post["account"]["username"],
            "account_account": post["account"]["account"],
            "account_display_name": post["account"]["display_name"],
            "account_note": post["account"]["note"],
            "link_id": post["link"]["id"],
            "link_url": post["link"]["url"],
            "link_title": post["link"]["title"],
            "link_description": post["link"]["description"],
            "link_type": post["link"]["type"] if "type" in post["link"] else None,
            "link_image": post["link"]["image"],
            "image_id": post["image"]["id"],
            "image_url": post["image"]["url"],
            "image_type": post["image"]["type"] if "type" in post["image"] else None,
            "thread_id": post["id"],
            "timestamp": post_time.strftime("%Y-%m-%d %H:%M:%S")
        }        
    
        return mapped_item
