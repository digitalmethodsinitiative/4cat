"""
Import scraped Threads data

It's prohibitively difficult to scrape data from Threads within 4CAT itself due
to its aggressive rate limiting. Instead, import data collected elsewhere.
"""
from datetime import datetime
from urllib.parse import urlparse, parse_qs, unquote
import re

from backend.lib.search import Search
from common.lib.item_mapping import MappedItem


class SearchThreads(Search):
    """
    Import scraped Threads data
    """
    type = "threads-search"  # job ID
    category = "Search"  # category
    title = "Import scraped Threads data"  # title displayed in UI
    description = "Import Threads data collected with an external tool such as Zeeschuimer."  # description displayed in UI
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

        Not available for 9gag
        """
        raise NotImplementedError("Threads datasets can only be created by importing data from elsewhere")

    @staticmethod
    def map_item(post):
        post_timestamp = datetime.fromtimestamp(post["taken_at"])

        if post["carousel_media"]:
            image_urls = [c["image_versions2"]["candidates"].pop(0)["url"] for c in post["carousel_media"] if c["image_versions2"]]
            video_urls = [c["video_versions"].pop(0)["url"] for c in post["carousel_media"] if c["video_versions"]]
        else:
            image_urls = [post["image_versions2"]["candidates"].pop(0)["url"]] if post["image_versions2"].get("candidates") else []
            video_urls = [post["video_versions"].pop(0)["url"]] if post["video_versions"] else []

        linked_url = ""
        link_thumbnail = ""
        if post["text_post_app_info"].get("link_preview_attachment"):
            linked_url = post["text_post_app_info"]["link_preview_attachment"]["url"]
            linked_url = parse_qs(urlparse(linked_url).query).get("u", "").pop()
            link_thumbnail = post["text_post_app_info"]["link_preview_attachment"].get("image_url")

        return MappedItem({
            "id": post["code"],
            "url": f"https://www.threads.net/@{post['user']['username']}/post/{post['code']}",
            "body": post["caption"]["text"] if post["caption"] else "",
            "timestamp": post_timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "author": post["user"]["username"],
            "author_is_verified": "yes" if post["user"].get("is_verified") else "no",
            "author_avatar": post["user"].get("profile_pic_url"),
            "image_url": ",".join(image_urls),
            "video_url": ",".join(video_urls),
            "link_url": linked_url,
            "link_thumbnail_url": link_thumbnail if link_thumbnail else "",
            "is_paid_partnership": "yes" if post["is_paid_partnership"] else "no",
            "likes": post["like_count"],
            "reposts": post["text_post_app_info"]["repost_count"],
            "replies": post["text_post_app_info"]["direct_reply_count"],
            "quotes": post["text_post_app_info"]["quote_count"],
            "hashtags": ",".join(re.findall(r"#([^\s!@#$%ˆ&*()_+{}:\"|<>?\[\];'\,./`~']+)", post["caption"]["text"])) if post["caption"] else "",
            "unix_timestamp": int(post_timestamp.timestamp()),
        })
