"""
Import scraped Weibo comments

Weibo shows little to visitors who are not logged in, and 4CAT cannot log in
to it, so comments are collected elsewhere and imported, typically with
Zeeschuimer.
"""
from datetime import datetime, timezone

from backend.lib.search import Search
from common.lib.exceptions import MapItemException
from common.lib.item_mapping import MappedItem, MissingMappedField, value_or_missing
from common.lib.helpers import normalize_url_encoding, strip_tags


class SearchWeiboComments(Search):
    """
    Import scraped Weibo comment data
    """
    type = "weibo-comments-search"  # job ID
    category = "Search"  # category
    title = "Import scraped Weibo comment data"  # title displayed in UI
    description = "Import Weibo comment data collected with an external tool such as Zeeschuimer."  # description displayed in UI
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
        raise NotImplementedError("Weibo comment datasets can only be created by importing data from elsewhere")

    @staticmethod
    def map_item(comment):
        """
        Map a Weibo comment to a 4CAT item

        Top-level comments and replies have the same format. A reply's
        `rootidstr` is the ID of the comment its thread starts with, and
        `reply_comment` a copy of the comment it answers.

        :param dict comment:  Comment as collected, with `__import_meta`
        :return MappedItem:
        """
        if not weibo_is_comment(comment):
            source = comment.get("__import_meta", {}).get("source_url", "")
            raise MapItemException(f"Not a Weibo comment (source: {source or 'unknown'})")

        user = comment["user"]
        post = weibo_commented_post(comment)
        is_reply = comment["rootidstr"] != comment["idstr"]
        try:
            unix_timestamp = int(datetime.strptime(comment["created_at"], "%a %b %d %H:%M:%S %z %Y").timestamp())
        except (TypeError, ValueError):
            unix_timestamp = None
        reply_to = comment.get("reply_comment") or {}

        return MappedItem({
            "collected_from_url": normalize_url_encoding(comment.get("__import_meta", {}).get("source_platform_url", "")),
            "id": comment["idstr"],
            "thread_id": post["id"] if post["id"] is not None else MissingMappedField(""),
            "post_id": post["id"] if post["id"] is not None else MissingMappedField(""),
            "post_url": f"https://weibo.com/{post['author_id']}/{post['id']}"
                if post["id"] and post["author_id"] else MissingMappedField(""),
            "author": user.get("screen_name", ""),
            "author_id": user["idstr"],
            "author_avatar_url": weibo_first_set(user.get("avatar_hd"), user.get("profile_image_url"), ""),
            "body": comment["text_raw"] if isinstance(comment.get("text_raw"), str)
                else strip_tags(comment.get("text") or ""),
            "timestamp": datetime.fromtimestamp(unix_timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                if unix_timestamp is not None else MissingMappedField(""),
            "unix_timestamp": unix_timestamp if unix_timestamp is not None else MissingMappedField(""),
            "likes": weibo_first_set(comment.get("like_counts"), comment.get("like_count"), MissingMappedField("")),
            "replies": "" if is_reply else value_or_missing(comment, "total_number", ""),
            "is_reply": "yes" if is_reply else "no",
            "root_comment_id": comment["rootidstr"],
            "reply_to_comment_id": weibo_first_set(reply_to.get("idstr"), ""),
            "reply_to_author": weibo_first_set((reply_to.get("user") or {}).get("screen_name"), ""),
            "location": comment["source"].removeprefix("来自").lstrip()
                if comment.get("source") else MissingMappedField(""),
            "is_liked_by_post_author": "yes" if comment.get("isLikedByMblogAuthor") else "no",
        })


def weibo_is_comment(item):
    """
    Whether an object is a Weibo comment

    Comments have their own ID, the ID of the comment their thread starts with
    (their own, for a top-level comment), an author and a creation date.

    :param item:
    :return bool:
    """
    return isinstance(item, dict) \
        and isinstance(item.get("idstr"), str) \
        and isinstance(item.get("rootidstr"), str) \
        and isinstance(item.get("user"), dict) \
        and isinstance(item.get("created_at"), str)


def weibo_commented_post(comment):
    """
    The post a comment belongs to

    Comments do not name their post in a field of its own. Its ID and its
    author's ID are in `analysis_extra`, which reads like
    "author_uid:5781292544|mid:5353703604491306|rid:5246087537427886552".

    :param dict comment:
    :return dict:  `id` and `author_id`, either None when not found
    """
    fields = dict(field.split(":", 1) for field in str(comment.get("analysis_extra") or "").split("|")
                  if ":" in field)

    return {"id": fields.get("mid"), "author_id": fields.get("author_uid")}


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