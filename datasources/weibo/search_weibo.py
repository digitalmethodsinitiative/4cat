"""
Import scraped Weibo posts

Weibo shows little to visitors who are not logged in, and 4CAT cannot log in
to it, so posts are collected elsewhere and imported, typically with
Zeeschuimer.
"""
import re

from datetime import datetime, timezone

from backend.lib.search import Search
from common.lib.exceptions import MapItemException
from common.lib.item_mapping import MappedItem, MissingMappedField, value_or_missing
from common.lib.helpers import normalize_url_encoding, strip_tags


class SearchWeibo(Search):
    """
    Import scraped Weibo data
    """
    type = "weibo-search"  # job ID
    category = "Search"  # category
    title = "Import scraped Weibo data"  # title displayed in UI
    description = "Import Weibo data collected with an external tool such as Zeeschuimer."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_from_zeeschuimer = True

    # not available as a processor for existing datasets
    accepts = [None]
    references = [
        "[Zeeschuimer browser extension](https://github.com/digitalmethodsinitiative/zeeschuimer)"
    ]

    def get_items(self, query):
        """
        Run custom search

        Not available for Weibo
        """
        raise NotImplementedError("Weibo datasets can only be created by importing data from elsewhere")

    @staticmethod
    def map_item(post):
        """
        Map a Weibo post to a 4CAT item

        Posts have the same format wherever Zeeschuimer collects them on
        weibo.com, except that posts from super-topic pages have no
        `text_raw`. A repost carries the post it reposts in
        `retweeted_status`.

        :param dict post:  Post as collected, with `__import_meta`
        :return MappedItem:
        """
        if not weibo_is_post(post):
            source = post.get("__import_meta", {}).get("source_url", "")
            raise MapItemException(f"Not a Weibo post (source: {source or 'unknown'})")

        user = post["user"]
        reposted = post.get("retweeted_status")
        try:
            unix_timestamp = int(datetime.strptime(post["created_at"], "%a %b %d %H:%M:%S %z %Y").timestamp())
        except (TypeError, ValueError):
            unix_timestamp = None
        reposted_user = reposted.get("user") if reposted is not None else None

        return MappedItem({
            "collected_from_url": normalize_url_encoding(post.get("__import_meta", {}).get("source_platform_url", "")),
            "id": post["idstr"],
            "thread_id": post["idstr"],
            "url": f"https://weibo.com/{user['idstr']}/{post['mblogid']}",
            "body": weibo_post_text(post),
            "body_is_shortened": "yes" if weibo_is_shortened(post) else "no",
            "timestamp": datetime.fromtimestamp(unix_timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                if unix_timestamp is not None else MissingMappedField(""),
            "unix_timestamp": unix_timestamp if unix_timestamp is not None else MissingMappedField(""),
            "author": user.get("screen_name", ""),
            "author_id": user["idstr"],
            "author_avatar_url": weibo_first_set(user.get("avatar_hd"), user.get("profile_image_url"), ""),
            "author_verified": "yes" if user.get("verified") else "no",
            "author_followers": value_or_missing(user, "followers_count", ""),
            "likes": value_or_missing(post, "attitudes_count", 0),
            "comments": value_or_missing(post, "comments_count", 0),
            "reposts": value_or_missing(post, "reposts_count", 0),
            "hashtags": ",".join(weibo_hashtags(post)),
            "image_urls": ",".join(weibo_image_urls(post)),
            "video_url": weibo_video_url(post),
            "location": post["region_name"].removeprefix("发布于").lstrip()
                if post.get("region_name") else MissingMappedField(""),
            "posted_with": strip_tags(post["source"]) if post.get("source") else "",
            "is_promoted": "yes" if post.get("isAd") else "no",
            "is_repost": "yes" if reposted is not None else "no",
            "reposted_id": reposted.get("idstr", "") if reposted is not None else "",
            "reposted_url": f"https://weibo.com/{reposted_user['idstr']}/{reposted['mblogid']}"
                if isinstance(reposted_user, dict) else "",
            "reposted_author": reposted_user.get("screen_name", "") if isinstance(reposted_user, dict) else "",
            "reposted_body": weibo_post_text(reposted) if reposted is not None else "",
            "reposted_body_is_shortened": "yes" if reposted is not None and weibo_is_shortened(reposted) else "no",
        })


def weibo_is_post(item):
    """
    Whether an object is a Weibo post

    Posts have a short ID used in their URL (`mblogid`), an author and a
    creation date.

    :param item:
    :return bool:
    """
    return isinstance(item, dict) \
        and isinstance(item.get("mblogid"), str) \
        and isinstance(item.get("user"), dict) \
        and isinstance(item.get("created_at"), str)


def weibo_is_shortened(post):
    """
    Whether a post's text was cut short when it was collected

    Feeds and lists send only the start of a long post and set `isLongText`.
    A post's own page sends the full text as well, in `longText`.

    :param dict post:
    :return bool:
    """
    return post.get("isLongText") is True and not post.get("longText")


def weibo_first_set(*values):
    """
    The first value that is not None

    :param values:  Candidates, in order of preference; the last is the fallback
    :return:
    """
    for value in values:
        if value is not None:
            return value
    return values[-1]


def weibo_post_text(post):
    """
    A post's text, in full when it was collected in full

    `text_raw` is plain text, `text` the same with HTML links. Super-topic
    pages send only `text`.

    :param dict post:
    :return str:
    """
    long_text = post.get("longText")
    if isinstance(long_text, dict) and long_text.get("content"):
        return long_text["content"]

    if isinstance(post.get("text_raw"), str):
        return post["text_raw"]

    return strip_tags(post.get("text") or "")


def weibo_hashtags(post):
    """
    Hashtags in a post, without the # on either side

    Weibo hashtags are enclosed in #, as in #广交会#. `topic_struct` lists
    them when present.

    :param dict post:
    :return list:
    """
    topics = post.get("topic_struct")
    if isinstance(topics, list) and topics:
        return [topic["topic_title"] for topic in topics if topic.get("topic_title")]

    return re.findall(r"#([^#\n]+)#", weibo_post_text(post))


def weibo_image_urls(post):
    """
    Full-size image URLs, in the order the post shows them

    Images are in `pic_infos`, keyed by the IDs in `pic_ids`; posts that mix
    images and videos have them in `mix_media_info` instead.

    :param dict post:
    :return list:
    """
    pictures = []
    pic_infos = post.get("pic_infos") or {}
    for pic_id in post.get("pic_ids") or []:
        if pic_infos.get(pic_id):
            pictures.append(pic_infos[pic_id])

    for media in (post.get("mix_media_info") or {}).get("items") or []:
        if media.get("type") == "pic" and media.get("data"):
            pictures.append(media["data"])

    urls = []
    for picture in pictures:
        url = weibo_first_set(
            (picture.get("largest") or {}).get("url"),
            (picture.get("original") or {}).get("url"),
            (picture.get("large") or {}).get("url"),
            None
        )
        if url and url not in urls:
            urls.append(url)

    return urls


def weibo_video_url(post):
    """
    URL of a post's video, if it has one

    :param dict post:
    :return str:
    """
    pages = [post.get("page_info")]
    for media in (post.get("mix_media_info") or {}).get("items") or []:
        if media.get("type") == "video":
            pages.append(media.get("data"))

    for page in pages:
        if not isinstance(page, dict) or page.get("object_type") != "video":
            continue
        media_info = page.get("media_info") or {}
        url = media_info.get("mp4_720p_mp4") or media_info.get("mp4_hd_url") \
            or media_info.get("stream_url_hd") or media_info.get("stream_url")
        if url:
            return url

    return ""
