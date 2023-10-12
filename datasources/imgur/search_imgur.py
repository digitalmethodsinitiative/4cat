"""
Import scraped Imgur data

It's prohibitively difficult to scrape data from Imgur within 4CAT itself due
to its aggressive rate limiting. Instead, import data collected elsewhere.
"""
from datetime import datetime

from backend.lib.search import Search


class SearchNineGag(Search):
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
    def map_item(post):
        post_timestamp = datetime.strptime(post["created_at"], "%Y-%m-%dT%H:%M:%SZ")

        return {
            "id": post["id"],
            "subject": post["title"],
            "body": post["description"],
            "timestamp": post_timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "author": post["account_id"],
            "type": post["cover"]["type"],
            "media_url": post["cover"]["url"],
            "post_url": post["url"],
            "album_media": post["image_count"],
            "is_ad": "no" if not post["is_ad"] else "yes",
            "is_album": "no" if not post["is_album"] else "yes",
            "is_mature": "no" if not post["is_mature"] else "yes",
            "is_viral": "no" if not post["in_most_viral"] else "yes",
            "views": post["view_count"],
            "upvotes": post["upvote_count"],
            "downvotes": post["downvote_count"],
            "score": post["point_count"],
            "comments": post["comment_count"],
            "favourites": post["favorite_count"],
            "virality_score": post["virality"],
            "unix_timestamp": int(post_timestamp.timestamp()),
        }
