"""
Import scraped RedNote data

It's prohibitively difficult to scrape data from RedNote within 4CAT itself due
to its aggressive rate limiting. Instead, import data collected elsewhere.
"""
from datetime import datetime

from backend.lib.search import Search
from common.lib.item_mapping import MappedItem, MissingMappedField


class SearchRedNote(Search):
    """
    Import scraped RedNote/Xiaohongshu/XSH data
    """
    type = "xiaohongshu-search"  # job ID
    category = "Search"  # category
    title = "Import scraped RedNote data"  # title displayed in UI
    description = "Import RedNote data collected with an external tool such as Zeeschuimer."  # description displayed in UI
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
        raise NotImplementedError("RedNote/Xiaohongshu datasets can only be created by importing data from elsewhere")


    @staticmethod
    def map_item(post):
        """
        Map XSH object to 4CAT item

        Depending on whether the object was captured from JSON or HTML, treat it
        differently. A lot of data is missing from HTML objects.

        :param post:
        :return:
        """
        if post.get("_zs-origin") == "html":
            return SearchRedNote.map_item_from_html(post)
        else:
            if "note" in post:
                return SearchRedNote.map_item_from_json_embedded(post)
            else:
                return SearchRedNote.map_item_from_json_api_explore(post)

    @staticmethod
    def map_item_from_json_api_explore(post):
        """
        Map API-sourced XSH object to 4CAT item

        Most straightforward - JSON objects from the XSH web API, which do
        however not always contain the same fields.

        :param dict post:
        :return MappedItem:
        """
        item = post["note_card"] if post.get("type") != "video" else post
        item_id = post.get("id", post.get("note_id"))

        import json

        image = item["image_list"][0]["url_default"] if item.get("image_list") else item["cover"]["url_default"]

        # permalinks need this token to work, else you get a 404 not found
        xsec_bit = f"?xsec_token={post['xsec_token']}" if post.get("xsec_token") else ""
        if item.get("video"):
            video_url = item["video"]["media"]["stream"]["h264"][0]["master_url"]
        else:
            video_url = MissingMappedField("")

        timestamp = item.get("time", None)
        return MappedItem({
            "id": item_id,
            "url": f"https://www.xiaohongshu.com/explore/{post['id']}{xsec_bit}",
            "title": item.get("display_title", ""),
            "body": item.get("desc", "") if "desc" in item else MissingMappedField(""),
            "timestamp": datetime.fromtimestamp(timestamp / 1000).strftime("%Y-%m-%d %H:%M:%S") if timestamp else MissingMappedField(""),
            "author": item["user"]["nickname"],
            "author_avatar_url": item["user"]["avatar"],
            "image_url": image,
            "video_url": video_url,
            # only available when loading an individual post page, so skip
            # "tags": ",".join(t["name"] for t in item["tag_list"]),
            "likes": item["interact_info"]["liked_count"],
            # "collects": item["interact_info"]["collected_count"],
            # "comments": item["interact_info"]["comment_count"],
            # "shares": item["interact_info"]["share_count"],
            "unix_timestamp": int(timestamp / 1000) if timestamp else MissingMappedField(""),
        })

    @staticmethod
    def map_item_from_json_embedded(item):
        """
        Map JSON object from an XHS HTML page

        JSON objects from the HTML are formatted slightly differently, mostly
        in that they use camelCase instead of underscores, but we can also
        make a few more assumptions about the data

        :param dict item:
        :return MappedItem:
        """
        note = item["note"]
        image = note["imageList"][0]["urlDefault"]
        # permalinks need this token to work, else you get a 404 not found
        xsec_bit = f"?xsec_token={note['xsecToken']}"
        timestamp = item.get("time", None)

        return MappedItem({
            "id": item["id"],
            "url": f"https://www.xiaohongshu.com/explore/{item['id']}{xsec_bit}",
            "title": note.get("title", ""),
            "body": note.get("desc", "") if "desc" in note else MissingMappedField(""),
            "timestamp": datetime.fromtimestamp(timestamp / 1000).strftime("%Y-%m-%d %H:%M:%S") if timestamp else MissingMappedField(""),
            "author": note["user"]["nickname"],
            "author_avatar_url": note["user"]["avatar"],
            "image_url": image,
            "video_url": MissingMappedField(""),
            # only available when loading an individual post page, so skip
            # "tags": ",".join(t["name"] for t in item["tag_list"]),
            "likes": item["interactInfo"]["likedCount"],
            # "collects": item["interact_info"]["collected_count"],
            # "comments": item["interact_info"]["comment_count"],
            # "shares": item["interact_info"]["share_count"],
            "unix_timestamp": int(timestamp / 1000) if timestamp else MissingMappedField(""),
        })

    def map_item_from_html(item):
        """
        Map pre-mapped item

        These have been mapped by Zeeschuimer from the page HTML and contain
        less data than JSON objects (but enough to be useful in some cases).

        :param dict item:
        :return MappedItem:
        """
        return MappedItem({
            "id": item["id"],
            "url": f"https://www.xiaohongshu.com{item['url']}",
            "title": item["title"],
            "body": MissingMappedField(""),
            "timestamp": MissingMappedField(""),
            "author": item["author_name"],
            "author_avatar_url": item["author_avatar_url"],
            "image_url": item["thumbnail_url"],
            "video_url": MissingMappedField(""),
            # "tags": MissingMappedField(""),
            "likes": item["likes"],
            # "collects": MissingMappedField(""),
            # "comments": MissingMappedField(""),
            # "shares": MissingMappedField(""),
            "unix_timestamp": MissingMappedField(""),
        })
