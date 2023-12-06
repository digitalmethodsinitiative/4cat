"""
Import scraped TikTok data

It's prohibitively difficult to scrape data from TikTok within 4CAT itself due
to its aggressive rate limiting. Instead, import data collected elsewhere.
"""
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

from backend.lib.search import Search


class SearchTikTok(Search):
    """
    Import scraped TikTok data
    """
    type = "tiktok-search"  # job ID
    category = "Search"  # category
    title = "Import scraped Tiktok data"  # title displayed in UI
    description = "Import Tiktok data collected with an external tool such as Zeeschuimer."  # description displayed in UI
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

        Not available for TikTok
        """
        raise NotImplementedError("TikTok datasets can only be created by importing data from elsewhere")

    @staticmethod
    def map_item(post):
        challenges = [challenge["title"] for challenge in post.get("challenges", [])]

        hashtags = [extra["hashtagName"] for extra in post.get("textExtra", []) if
                    "hashtagName" in extra and extra["hashtagName"]]

        labels = ",".join(post["diversificationLabels"]) if type(post.get("diversificationLabels")) is list else ""

        if type(post.get("author")) is dict:
            # from intercepted API response
            user_nickname = post["author"]["uniqueId"]
            user_fullname = post["author"]["nickname"]
            user_id = post["author"]["id"]
        elif post.get("author"):
            # from embedded JSON object
            user_nickname = post["author"]
            user_fullname = post["nickname"]
            user_id = ""
        else:
            user_nickname = ""
            user_fullname = ""
            user_id = ""

        # there are various thumbnail URLs, some of them expire later than
        # others. Try to get the highest-resolution one that hasn't expired
        # yet
        thumbnail_options = []

        if post["video"].get("shareCover"):
            thumbnail_options.append(post["video"]["shareCover"].pop())

        if post["video"].get("cover"):
            thumbnail_options.append(post["video"]["cover"])

        now = int(datetime.now(tz=timezone.utc).timestamp())
        thumbnail_url = [url for url in thumbnail_options if int(parse_qs(urlparse(url).query).get("x-expires", [now])[0]) >= now]
        thumbnail_url = thumbnail_url.pop() if thumbnail_url else ""

        return {
            "id": post["id"],
            "thread_id": post["id"],
            "author": user_nickname,
            "author_full": user_fullname,
            "author_followers": post.get("authorStats", {}).get("followerCount", ""),
            "author_likes": post.get("authorStats", {}).get("diggCount", ""),
            "author_videos": post.get("authorStats", {}).get("videoCount", ""),
            "author_avatar": post.get("avatarThumb", ""),
            "body": post["desc"],
            "timestamp": datetime.utcfromtimestamp(int(post["createTime"])).strftime('%Y-%m-%d %H:%M:%S'),
            "unix_timestamp": int(post["createTime"]),
            "is_duet": "yes" if (post.get("duetInfo", {}).get("duetFromId") != "0" if post.get("duetInfo", {}) else False) else "no",
            "is_ad": "yes" if post.get("isAd", False) else "no",
            "music_name": post["music"]["title"],
            "music_id": post["music"]["id"],
            "music_url": post["music"].get("playUrl", ""),
            "music_thumbnail": post["music"].get("coverLarge", ""),
            "music_author": post["music"].get("authorName", ""),
            "video_url": post["video"].get("downloadAddr", ""),
            "tiktok_url": "https://www.tiktok.com/@%s/video/%s" % (user_nickname, post["id"]),
            "thumbnail_url": thumbnail_url,
            "likes": post["stats"]["diggCount"],
            "comments": post["stats"]["commentCount"],
            "shares": post["stats"]["shareCount"],
            "plays": post["stats"]["playCount"],
            "hashtags": ",".join(hashtags),
            "challenges": ",".join(challenges),
            "diversification_labels": labels,
            "location_created": post.get("locationCreated", ""),
            "stickers": "\n".join(" ".join(s["stickerText"]) for s in post.get("stickersOnItem", [])),
            "effects": ",".join([e["name"] for e in post.get("effectStickers", [])]),
            "warning": ",".join([w["text"] for w in post.get("warnInfo", [])])
        }
