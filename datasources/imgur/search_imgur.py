"""
Import scraped Imgur data

It's prohibitively difficult to scrape data from Imgur within 4CAT itself due
to its aggressive rate limiting. Instead, import data collected elsewhere.
"""
from datetime import datetime

from backend.lib.search import Search
from common.lib.item_mapping import MappedItem
from common.lib.helpers import UserInput

class SearchImgur(Search):
    """
    Import scraped Imgur data
    """
    type = "imgur-search"  # job ID
    category = "Search"  # category
    title = "Import scraped Imgur data"  # title displayed in UI
    description = "Import Imgur data collected with an external tool such as Zeeschuimer."  # description displayed in UI
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

        Not available for Imgur
        """
        raise NotImplementedError("Imgur datasets can only be created by importing data from elsewhere")

    @staticmethod
    def map_item(item):
        post_timestamp = datetime.strptime(item["created_at"], "%Y-%m-%dT%H:%M:%SZ")

        return MappedItem({
            "id": item["id"],
            "subject": item["title"],
            "body": item["description"],
            "timestamp": post_timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "author": item["account_id"],
            "type": item["cover"]["type"],
            "media_url": item["cover"]["url"],
            "post_url": item["url"],
            "album_media": item["image_count"],
            "is_ad": "no" if not item["is_ad"] else "yes",
            "is_album": "no" if not item["is_album"] else "yes",
            "is_mature": "no" if not item["is_mature"] else "yes",
            "is_viral": "no" if not item["in_most_viral"] else "yes",
            "views": item["view_count"],
            "upvotes": item["upvote_count"],
            "downvotes": item["downvote_count"],
            "score": item["point_count"],
            "comments": item["comment_count"],
            "favourites": item["favorite_count"],
            "virality_score": item["virality"],
            "unix_timestamp": int(post_timestamp.timestamp()),
        })