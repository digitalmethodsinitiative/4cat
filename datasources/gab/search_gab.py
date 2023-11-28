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
            "type": post["type"],
            "created_at": post["created_at"],
            "thread_id": post["id"],
            "timestamp": post_time.strftime("%Y-%m-%d %H:%M:%S"),
            "url": post["url"],
            "post_id": "",
            "body": "",
            "reaction_count": "",
            "reposts_count": "",
            "replies_count": "",
            "account_id": "",
            "account_username": "",
            "account_display_name": "",
            "account_url": "",
            "group_id": "",
            "group_title": "",
            "group_description": "",
            "group_member_count": "",
            "group_is_verified": "",
            "group_is_private": "",
            "group_category": "",
            "account_note": "",
            "account_followers_count": "",
            "account_following_count": "",
            "account_statuses_count": "",
            "account_is_pro": "",
            "account_is_verified": "",
            "account_is_donor": "",
            "account_is_investor": "",
            "account_show_pro_life": "",
            "account_is_parody": ""
        }

        
        if post["type"] == "post":
            mapped_item["post_id"] = post["id"]
            mapped_item["body"] = post["content"]
            mapped_item["reaction_count"] = post["reaction_count"]
            mapped_item["reposts_count"] = post["reposts_count"]
            mapped_item["replies_count"] = post["replies_count"]
            
            ### poster-specific
            mapped_item["account_id"] = post["account"]["id"] 
            mapped_item["account_username"] = post["account"]["username"]
            mapped_item["account_display_name"] = post["account"]["display_name"]
            mapped_item["account_url"] = post["account"]["url"]

        if post["type"] == "group":
            mapped_item["group_id"] = post["id"]
            mapped_item["body"] = post["account"]["title"]
            mapped_item["group_title"] = post["account"]["title"]
            mapped_item["group_description"] = post["account"]["description"]
            mapped_item["group_member_count"] = post["account"]["member_count"]
            mapped_item["group_is_verified"] = post["account"]["is_verified"]
            mapped_item["group_is_private"] = post["account"]["is_private"]
            mapped_item["group_category"] = post["account"]["category"]


        if post["type"] == "user":
            mapped_item["account_id"] = post["id"]
            mapped_item["account_username"] = post["account"]["username"]
            mapped_item["account_display_name"] = post["account"]["display_name"]
            mapped_item["account_url"] = post["account"]["url"]
            mapped_item["account_note"] = post["account"]["note"]
            mapped_item["account_avatar"] = post["account"]["avatar"]
            mapped_item["account_followers_count"] = post["account"]["followers_count"]
            mapped_item["account_following_count"] = post["account"]["following_count"]
            mapped_item["account_statuses_count"] = post["account"]["statuses_count"]
            mapped_item["account_is_pro"] = post["account"]["is_pro"]
            mapped_item["account_is_verified"] = post["account"]["is_verified"]
            mapped_item["account_is_donor"] = post["account"]["is_donor"]
            mapped_item["account_is_investor"] = post["account"]["is_investor"]
            mapped_item["account_show_pro_life"] = post["account"]["show_pro_life"]
            mapped_item["account_is_parody"] = post["account"]["is_parody"]
        
    
        return mapped_item
