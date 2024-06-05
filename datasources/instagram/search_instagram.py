"""
Import scraped Instagram data

It's prohibitively difficult to scrape data from Instagram within 4CAT itself
due to its aggressive rate limiting. Instead, import data collected elsewhere.
"""
import datetime
import re

from backend.lib.search import Search
from common.lib.item_mapping import MappedItem, MissingMappedField
from common.lib.exceptions import WorkerInterruptedException, MapItemException


class SearchInstagram(Search):
    """
    Import scraped Instagram data
    """
    type = "instagram-search"  # job ID
    category = "Search"  # category
    title = "Import scraped Instagram data"  # title displayed in UI
    description = "Import Instagram data collected with an external tool such as Zeeschuimer."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_from_extension = True

    # not available as a processor for existing datasets
    accepts = [None]
    references = [
        "[Zeeschuimer browser extension](https://github.com/digitalmethodsinitiative/zeeschuimer)",
        "[Worksheet: Capturing TikTok data with Zeeschuimer and 4CAT](https://tinyurl.com/nmrw-zeeschuimer-tiktok) (also covers usage with Instagram)"
    ]

    # some magic numbers instagram uses
    MEDIA_TYPE_PHOTO = 1
    MEDIA_TYPE_VIDEO = 2
    MEDIA_TYPE_CAROUSEL = 8

    def get_items(self, query):
        """
        Run custom search

        Not available for Instagram
        """
        raise NotImplementedError("Instagram datasets can only be created by importing data from elsewhere")


    @staticmethod
    def map_item(item):
        """
        Map Instagram item

        Instagram importing is a little bit roundabout since we can expect
        input in two separate and not completely overlapping formats - an "edge
        list" or an "item list", and posts are structured differently between
        those, and do not contain the same data. So we find a middle ground
        here... each format has its own handler function

        :param dict item:  Item to map
        :return:  Mapped item
        """
        link = item.get("link", "")
        if (item.get("product_type", "") == "ad") or \
                (link and link.startswith("https://www.facebook.com/ads/ig_redirect")):
            # These are ads
            raise MapItemException("appears to be Instagram ad, check raw data to confirm and ensure Zeeschuimer is up to date.")

        is_graph_response = "__typename" in item and item["__typename"] not in ("XDTMediaDict",)

        if is_graph_response:
            return MappedItem(SearchInstagram.parse_graph_item(item))
        else:
            return MappedItem(SearchInstagram.parse_itemlist_item(item))

    @staticmethod
    def parse_graph_item(node):
        """
        Parse Instagram post in Graph format

        :param node:  Data as received from Instagram
        :return dict:  Mapped item
        """
        try:
            caption = node["edge_media_to_caption"]["edges"][0]["node"]["text"]
        except IndexError:
            caption = MissingMappedField("")

        num_media = 1 if node["__typename"] != "GraphSidecar" else len(node["edge_sidecar_to_children"]["edges"])

        # get media url
        # for carousels, get the first media item, for videos, get the video
        # url, for photos, get the highest resolution
        if node["__typename"] == "GraphSidecar":
            media_node = node["edge_sidecar_to_children"]["edges"][0]["node"]
        else:
            media_node = node

        if media_node["__typename"] == "GraphVideo":
            media_url = media_node["video_url"]
        elif media_node["__typename"] == "GraphImage":
            resources = media_node.get("display_resources", media_node.get("thumbnail_resources"))
            try:
                media_url = resources.pop()["src"]
            except AttributeError:
                media_url = media_node.get("display_url", "")
        else:
            media_url = media_node["display_url"]

        # type, 'mixed' means carousel with video and photo
        type_map = {"GraphSidecar": "photo", "GraphVideo": "video"}
        if node["__typename"] != "GraphSidecar":
            media_type = type_map.get(node["__typename"], "unknown")
        else:
            media_types = set([s["node"]["__typename"] for s in node["edge_sidecar_to_children"]["edges"]])
            media_type = "mixed" if len(media_types) > 1 else type_map.get(media_types.pop(), "unknown")

        location = {"name": MissingMappedField(""), "latlong": MissingMappedField(""), "city": MissingMappedField("")}
        # location has 'id', 'has_public_page', 'name', and 'slug' keys in tested examples; no lat long or "city" though name seems
        if node.get("location"):
            location["name"] = node["location"].get("name")
            # Leaving this though it does not appear to be used in this type; maybe we'll be surprised in the future...
            location["latlong"] = str(node["location"]["lat"]) + "," + str(node["location"]["lng"]) if node[
                "location"].get("lat") else ""
            location["city"] = node["location"].get("city")

        user = node.get("user")
        owner = node.get("owner")
        if node.get("user") and node.get("owner"):
            if user.get("username") != owner.get("username"):
                raise MapItemException("Unable to parse item: different user and owner")

        mapped_item = {
            "id": node["shortcode"],
            "post_source_domain": node.get("__import_meta", {}).get("source_platform_url"),  # Zeeschuimer metadata
            "thread_id": node["shortcode"],
            "parent_id": node["shortcode"],
            "body": caption,
            "timestamp": datetime.datetime.fromtimestamp(node["taken_at_timestamp"]).strftime("%Y-%m-%d %H:%M:%S"),
            "author": user.get("username", owner.get("username", MissingMappedField(""))),
            "author_fullname": user.get("full_name", owner.get("full_name", MissingMappedField(""))),
            "author_avatar_url": user.get("profile_pic_url", owner.get("profile_pic_url", MissingMappedField(""))),
            "type": media_type,
            "url": "https://www.instagram.com/p/" + node["shortcode"],
            "image_url": node["display_url"],
            "media_url": media_url,
            "hashtags": ",".join(re.findall(r"#([^\s!@#$%ˆ&*()_+{}:\"|<>?\[\];'\,./`~']+)", caption)),
            # "usertags": ",".join(
            #     [u["node"]["user"]["username"] for u in node["edge_media_to_tagged_user"]["edges"]]),
            "num_likes": node["edge_media_preview_like"]["count"],
            "num_comments": node.get("edge_media_preview_comment", {}).get("count", 0),
            "num_media": num_media,
            "location_name": location["name"],
            "location_latlong": location["latlong"],
            "location_city": location["city"],
            "unix_timestamp": node["taken_at_timestamp"]
        }

        return mapped_item

    @staticmethod
    def parse_itemlist_item(node):
        """
        Parse Instagram post in 'item list' format

        :param node:  Data as received from Instagram
        :return dict:  Mapped item
        """
        num_media = 1 if node["media_type"] != SearchInstagram.MEDIA_TYPE_CAROUSEL else len(node["carousel_media"])
        caption = MissingMappedField("") if not "caption" in node else "" if not node.get("caption") else node["caption"]["text"]

        # get media url
        # for carousels, get the first media item, for videos, get the video
        # url, for photos, get the highest resolution
        if node["media_type"] == SearchInstagram.MEDIA_TYPE_CAROUSEL:
            media_node = node["carousel_media"][0]
        else:
            media_node = node

        if media_node["media_type"] == SearchInstagram.MEDIA_TYPE_VIDEO:
            media_url = media_node["video_versions"][0]["url"]
            if "image_versions2" in media_node:
                display_url = media_node["image_versions2"]["candidates"][0]["url"]
            else:
                # no image links at all :-/
                # video is all we have
                display_url = media_node["video_versions"][0]["url"]
        elif media_node["media_type"] == SearchInstagram.MEDIA_TYPE_PHOTO and media_node.get("image_versions2"):
            media_url = media_node["image_versions2"]["candidates"][0]["url"]
            display_url = media_url
        else:
            media_url = MissingMappedField("")
            display_url = MissingMappedField("")

        # type, 'mixed' means carousel with video and photo
        type_map = {SearchInstagram.MEDIA_TYPE_PHOTO: "photo", SearchInstagram.MEDIA_TYPE_VIDEO: "video"}
        if node["media_type"] != SearchInstagram.MEDIA_TYPE_CAROUSEL:
            media_type = type_map.get(node["media_type"], "unknown")
        else:
            media_types = set([s["media_type"] for s in node["carousel_media"]])
            media_type = "mixed" if len(media_types) > 1 else type_map.get(media_types.pop(), "unknown")

        if "comment_count" in node:
            num_comments = node["comment_count"]
        elif "comments" in node and type(node["comments"]) is list:
            num_comments = len(node["comments"])
        else:
            num_comments = -1

        location = {"name": MissingMappedField(""), "latlong": MissingMappedField(""), "city": MissingMappedField("")}
        if node.get("location"):
            location["name"] = node["location"].get("name")
            location["latlong"] = str(node["location"]["lat"]) + "," + str(node["location"]["lng"]) if node[
                "location"].get("lat") else ""
            location["city"] = node["location"].get("city")

        user = node.get("user", {})
        owner = node.get("owner", {})
        if user and owner:
            if user.get("username") != owner.get("username"):
                raise MapItemException("Unable to parse item: different user and owner")

        mapped_item = {
            "id": node["code"],
            "post_source_domain": node.get("__import_meta", {}).get("source_platform_url"), # Zeeschuimer metadata
            "thread_id": node["code"],
            "parent_id": node["code"],
            "body": caption,
            "author": user.get("username", owner.get("username", MissingMappedField(""))),
            "author_fullname": user.get("full_name", owner.get("full_name", MissingMappedField(""))),
            "author_avatar_url": user.get("profile_pic_url", owner.get("profile_pic_url", MissingMappedField(""))),
            "timestamp": datetime.datetime.fromtimestamp(node["taken_at"]).strftime("%Y-%m-%d %H:%M:%S"),
            "type": media_type,
            "url": "https://www.instagram.com/p/" + node["code"],
            "image_url": display_url,
            "media_url": media_url,
            "hashtags": ",".join(re.findall(r"#([^\s!@#$%ˆ&*()_+{}:\"|<>?\[\];'\,./`~']+)", caption)),
            # "usertags": ",".join(
            #     [u["node"]["user"]["username"] for u in node["edge_media_to_tagged_user"]["edges"]]),
            "num_likes": node["like_count"],
            "num_comments": num_comments,
            "num_media": num_media,
            "location_name": location["name"],
            "location_latlong": location["latlong"],
            "location_city": location["city"],
            "unix_timestamp": node["taken_at"]
        }

        return mapped_item
