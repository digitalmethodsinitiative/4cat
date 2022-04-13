"""
Import scraped TikTok data

It's prohibitively difficult to scrape data from TikTok within 4CAT itself due
to its aggressive rate limiting. Instead, import data collected elsewhere.
"""
from pathlib import Path
import json
import re

from backend.abstract.search import Search
from common.lib.helpers import UserInput
from common.lib.exceptions import WorkerInterruptedException


class SearchTikTok(Search):
    """
    Import scraped TikTok data
    """
    type = "tiktok-search"  # job ID
    category = "Search"  # category
    title = "Import scraped Tiktok data"  # title displayed in UI
    description = "Import Tiktok data collected with an external tool such as Zeeschuimer."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI
    is_local = False    # Whether this datasource is locally scraped
    is_static = False   # Whether this datasource is still updated

    # not available as a processor for existing datasets
    accepts = [None]

    def get_items(self, query):
        """
        Run custom search

        Not available for TikTok
        """
        raise NotImplementedError("TikTok datasets can only be created by importing data from elsewhere")

    def import_from_file(self, path):
        """
        Import items from an external file

        By default, this reads a file and parses each line as JSON, returning
        the parsed object as an item. This works for NDJSON files. Data sources
        that require importing from other or multiple file types can overwrite
        this method.

        The file is considered disposable and deleted after importing.

        :param str path:  Path to read from
        :return:  Yields all items in the file, item for item.
        """
        path = Path(path)
        if not path.exists():
            return []

        with path.open() as infile:
            for line in infile:
                if self.interrupted:
                    raise WorkerInterruptedException()

                # remove NUL bytes here because they trip up a lot of other
                # things
                post = json.loads(line.replace("\0", ""))["data"]

                hashtags = [extra["hashtagName"] for extra in post.get("textExtra", []) if "hashtagName" in extra and extra["hashtagName"]]

                if type(post["author"]) is dict:
                    # from intercepted API response
                    user_nickname = post["author"]["uniqueId"]
                    user_fullname = post["author"]["nickname"]
                    user_id = post["author"]["id"]
                else:
                    # from embedded JSON object
                    user_nickname = post["author"]
                    user_fullname = post["nickname"]
                    user_id = ""


                mapped_item = {
                    "id": post["id"],
                    "thread_id": post["id"],
                    "author": user_nickname,
                    "author_full": user_fullname,
                    "author_id": user_id,
                    "author_followers": post["authorStats"]["followerCount"],
                    "body": post["desc"],
                    "timestamp": int(post["createTime"]),
                    "is_duet": post["duetInfo"].get("duetFromId") != "0",
                    "music_name": post["music"]["title"],
                    "music_id": post["music"]["id"],
                    "music_url": post["music"]["playUrl"],
                    "video_url": post["video"].get("downloadAddr", ""),
                    "tiktok_url": "https://tiktok.com/@%s/video/%s" % (user_nickname, post["id"]),
                    "thumbnail_url": post["video"]["cover"],
                    "likes": post["stats"]["diggCount"],
                    "comments": post["stats"]["commentCount"],
                    "shares": post["stats"]["shareCount"],
                    "plays": post["stats"]["playCount"],
                    "hashtags": ",".join(hashtags)
                }

                yield mapped_item

        path.unlink()
