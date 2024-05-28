"""
Import scraped TikTok comment data

It's prohibitively difficult to scrape data from TikTok within 4CAT itself due
to its aggressive rate limiting. Instead, import data collected elsewhere.
"""
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

from backend.lib.search import Search
from common.lib.item_mapping import MappedItem


class SearchTikTokComments(Search):
    """
    Import scraped TikTok comment data
    """
    type = "tiktok-comments-search"  # job ID
    category = "Search"  # category
    title = "Import scraped Tiktok comment data"  # title displayed in UI
    description = "Import Tiktok comment data collected with an external tool such as Zeeschuimer."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_from_extension = True

    # not available as a processor for existing datasets
    accepts = [None]
    references = [
        "[Zeeschuimer browser extension](https://github.com/digitalmethodsinitiative/zeeschuimer)",
        "[Worksheet: Capturing TikTok data with Zeeschuimer and 4CAT](https://tinyurl.com/nmrw-zeeschuimer-tiktok)"
    ]

    def get_items(self, query):
        """
        Run custom search

        Not available for TikTok comments
        """
        raise NotImplementedError("TikTok comment datasets can only be created by importing data from elsewhere")

    @staticmethod
    def map_item(item):
        item_datetime = datetime.fromtimestamp(item["create_time"]).strftime("%Y-%m-%d %H:%M:%S")
        thread_id = item["aweme_id"] if item["reply_id"] == "0" else item["reply_id"]
        avatar_url = item["user"]["avatar_thumb"]["url_list"][0]

        return MappedItem({
            "id": item["cid"],
            "thread_id": thread_id,
            "author": item["user"]["unique_id"],
            "author_full": item["user"]["nickname"],
            "author_avatar_url": avatar_url,
            "body": item["text"],
            "timestamp": item_datetime,
            "unix_timestamp": item["create_time"],
            "likes": item["digg_count"],
            "replies": item.get("reply_comment_total", 0),
            "post_id": item["aweme_id"],
            "post_url": item["share_info"]["url"].split(".html")[0],
            "post_body": item["share_info"]["title"],
            "comment_url": item["share_info"]["url"],
            "is_liked_by_post_author": "yes" if bool(item["author_pin"]) else "no",
            "is_sticky": "yes" if bool(item["stick_position"]) else "no",
            "is_comment_on_comment": "no" if bool(item["reply_id"] == "0") else "yes",
            "language_guess": item["comment_language"]
        })