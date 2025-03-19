"""
Import scraped RedNote comments

It's prohibitively difficult to scrape data from RedNote within 4CAT itself due
to its aggressive rate limiting. Instead, import data collected elsewhere.
"""
from datetime import datetime

from backend.lib.search import Search
from common.lib.item_mapping import MappedItem, MissingMappedField


class SearchRedNoteComments(Search):
    """
    Import scraped RedNote/Xiaohongshu/XSH comment data
    """
    type = "xiaohongshu-comments-search"  # job ID
    category = "Search"  # category
    title = "Import scraped RedNote comment data"  # title displayed in UI
    description = "Import RedNote comment data collected with an external tool such as Zeeschuimer."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_from_zeeschuimer = True

    # not available as a processor for existing datasets
    accepts = [None]
    references = [
        "[Zeeschuimer browser extension](https://github.com/digitalmethodsinitiative/zeeschuimer)",
        "[Worksheet: Capturing TikTok data with Zeeschuimer and 4CAT](https://tinyurl.com/nmrw-zeeschuimer-tiktok)"
    ]

    def get_items(self, query):
        """
        Run custom search

        Not available for RedNote
        """
        raise NotImplementedError("RedNote/Xiaohongshu comment datasets can only be created by importing data from elsewhere")


    @staticmethod
    def map_item(item):
        """
        Map XSH comment object to 4CAT item

        Depending on whether the object was captured from JSON or HTML, treat it
        differently. A lot of data is missing from HTML objects.

        :param item:
        :return:
        """

        timestamp = datetime.fromtimestamp(int(item["create_time"]) / 1000).strftime("%Y-%m-%d %H:%M:%S")

        return MappedItem({
            "id": item["id"],
            "thread_id": item["note_id"],
            "url": f"https://www.xiaohongshu.com/explore/{item['note_id']}",
            "body": item.get("content", ""),
            "timestamp": timestamp,
            "author": item["user_info"]["nickname"],
            "author_avatar_url": item["user_info"]["image"],
            "ip_location": item["ip_location"],
            "likes": item["like_count"],
            "replies": item["sub_comment_count"],
            "unix_timestamp": int(item["create_time"] / 1000)
        })
