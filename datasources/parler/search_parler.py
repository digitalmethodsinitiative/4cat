"""
Import scraped Parler data

It's prohibitively difficult to scrape data from Parler within 4CAT itself
due to its aggressive rate limiting and login wall. Instead, import data
collected elsewhere.
"""
import datetime
import re

from backend.lib.search import Search


class SearchParler(Search):
    """
    Import scraped LinkedIn data
    """
    type = "parler-search"  # job ID
    category = "Search"  # category
    title = "Import scraped Parler data"  # title displayed in UI
    description = "Import Parler data collected with an external tool such as Zeeschuimer."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_from_extension = True

    # not available as a processor for existing datasets
    accepts = [None]

    def get_items(self, query):
        """
        Run custom search

        Not available for Parler
        """
        raise NotImplementedError("Parler datasets can only be created by importing data from elsewhere")

    @staticmethod
    def map_item(node):
        """
        Parse Parler post

        :param node:  Data as received from Parler
        :return dict:  Mapped item
        """
        post = node["data"]
        post_time = datetime.datetime.strptime(post["date_created"], "%Y-%m-%dT%H:%M:%S.000000Z")

        mapped_item = {
            "id": post["postuuid"],
            "thread_id": post["postuuid"],
            "body": post["body"],
            "timestamp": post_time.strftime("%Y-%m-%d %H:%M:%S"),
            "author": post["user"]["username"],
            "author_name": post["user"]["name"],
            "author_followers": post["user"]["follower_count"],
            "detected_language": post["detected_language"],
            "views": post["views"],
            "echoes": post["echos"],
            "comments": post["total_comments"],
            "is_sensitive": "yes" if post["sensitive"] else "no",
            "is_echo": "yes" if post["is_echo"] else "no",
            "is_ad": "yes" if post["ad"] else "no",
            "hashtags": ",".join(re.findall(r"#([^\s!@#$%ˆ&*()_+{}:\"|<>?\[\];'\,./`~']+)", post["body"])),
            "image_url": post["image"] if post["image"] else "",
            "unix_timestamp": int(post_time.timestamp())
        }

        return mapped_item
