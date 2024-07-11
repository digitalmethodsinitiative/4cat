"""
Import scraped Gab data
"""
import datetime

from backend.lib.search import Search
from common.lib.item_mapping import MappedItem


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
        
        post_time = datetime.datetime.strptime(post["ca"], "%Y-%m-%dT%H:%M:%S.%fZ")
        mapped_item = {
            "id": post["i"],
            "created_at": post["ca"],
            "body": post["c"],
            "url": post["ul"],
            "reaction_count": post.get("fc", 0),
            "reposts_count": post["rbc"],
            "replies_count": post["rc"],
            "group_id": post["g"]["id"] if "g" in post else None,
            "group_title": post["g"]["title"] if "g" in post else None,
            "group_description": post["g"]["description"] if "g" in post else None,
            "group_member_count": post["g"]["member_count"] if "g" in post else None,
            "group_is_private": post["g"]["is_private"] if "g" in post else None,
            "group_url": post["g"]["url"] if "g" in post else None,
            "group_created_at": post["g"]["created_at"] if "g" in post else None,

            "account_id": post["author_info"]["i"],
            "account_username": post["author_info"]["un"],
            "account_account": post["author_info"]["ac"],
            "account_display_name": post["author_info"]["dn"],
            "account_note": post["author_info"]["nt"] if "nt" in post["author_info"] else None,

            "link_id": post["link_info"]["id"] if post["link_info"] else None,
            "link_url": post["link_info"]["url"] if post["link_info"] else None,
            "link_title": post["link_info"]["title"] if post["link_info"] else None,
            "link_description": post["link_info"]["description"] if post["link_info"] else None,
            "link_type": post["link_info"]["type"] if post["link_info"] else None,
            "link_image": post["link_info"]["image"] if post["link_info"] else None,


            "image_id": post["image_info"][0]["i"] if (len(post["image_info"]) > 0) else None,
            "image_url": post["image_info"][0]["u"] if (len(post["image_info"]) > 0) else None,
            "image_type": post["image_info"][0]["t"] if (len(post["image_info"]) > 0) else None,


            "thread_id": post["i"],
            "timestamp": post_time.strftime("%Y-%m-%d %H:%M:%S")
        }        
    
        return MappedItem(mapped_item)
