"""
Import scraped Instagram data

It's prohibitively difficult to scrape data from Instagram within 4CAT itself
due to its aggressive rate limiting. Instead, import data collected elsewhere.
"""
import datetime
import re

from backend.lib.search import Search
from common.lib.item_mapping import MappedItem, MissingMappedField
from common.lib.exceptions import MapItemException
from common.lib.helpers import normalize_url_encoding


class SearchInstagram(Search):
    """
    Import scraped Instagram data
    """
    type = "instagram-search"  # job ID
    category = "Search"  # category
    title = "Import scraped Instagram data"  # title displayed in UI
    description = "Import Instagram data collected with an external tool such as Zeeschuimer."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_from_zeeschuimer = True

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

        2025-6-5: potentially legacy format
        2026-2-10: much more confident legacy format no longer used

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

        location = {"name": "", "latlong": "", "city": "", "location_id": ""}
        # location has 'id', 'has_public_page', 'name', and 'slug' keys in tested examples; no lat long or "city" though name seems
        if node.get("location"):
            location["name"] = node["location"].get("name")
            location["location_id"] = node["location"].get("pk")
            # Leaving this though it does not appear to be used in this type; maybe we'll be surprised in the future...
            location["latlong"] = str(node["location"]["lat"]) + "," + str(node["location"]["lng"]) if node[
                "location"].get("lat") else ""
            location["city"] = node["location"].get("city")

        no_likes = bool(node.get("like_and_view_counts_disabled"))

        user = node.get("user")
        owner = node.get("owner")
        if node.get("user") and node.get("owner"):
            if owner.get("id") == user.get("id"):
                # Same id; owner may contain less info (e.g. no full name, username, etc.), so prefer user
                pass
            elif user.get("username") != owner.get("username"):
                raise MapItemException("Unable to parse item: different user and owner")

        mapped_item = {
            # Post data
            "id": node["shortcode"],
            "post_source_domain": node.get("__import_meta", {}).get("source_platform_url"),  # Zeeschuimer metadata
            "collected_from_view": node.get("_zs_instagram_view", MissingMappedField("")),
            "partial_item": node.get("_zs_partial", MissingMappedField("")),
            "timestamp": datetime.datetime.fromtimestamp(node["taken_at_timestamp"]).strftime("%Y-%m-%d %H:%M:%S"),
            "thread_id": node["shortcode"],
            "parent_id": node["shortcode"],
            "url": "https://www.instagram.com/p/" + node["shortcode"],
            "body": caption,


            # Author data
            "author": user.get("username", owner.get("username", MissingMappedField(""))),
            "author_fullname": user.get("full_name", owner.get("full_name", MissingMappedField(""))),
            "is_verified": True if user.get("is_verified") else False,
            "author_avatar_url": user.get("profile_pic_url", owner.get("profile_pic_url", MissingMappedField(""))),
            # Unable to find graph type posts to test
            "coauthors": MissingMappedField(""),
            "coauthor_fullnames": MissingMappedField(""),
            "coauthor_ids": MissingMappedField(""),

            # Media
            "media_type": media_type,
            "num_media": num_media,
            "image_urls": node["display_url"],
            "media_urls": media_url,

            # Engagement
            "hashtags": ",".join(re.findall(r"#([^\s!@#$%^&*()_+{}:\"|<>?\[\];'\,./`~]+)", caption)),
            # Unsure if usertags will work; need data (this could raise it to attention...)
            "usertags": ",".join(
                [u["node"]["user"]["username"] for u in node["edge_media_to_tagged_user"]["edges"]]),
            "likes_hidden": "yes" if no_likes else "no",
            "num_likes": node["edge_media_preview_like"]["count"] if not no_likes else MissingMappedField(0),
            "num_comments": node.get("edge_media_preview_comment", {}).get("count", 0),

            # Location data
            "location_name": location["name"],
            "location_id": location["location_id"],
            "location_latlong": location["latlong"],
            "location_city": location["city"],

            # Metadata
            "unix_timestamp": node["taken_at_timestamp"],
            "missing_media": None
        }

        return mapped_item

    @staticmethod
    def parse_itemlist_item(node):
        """
        Parse Instagram post in 'item list' format

        :param node:  Data as received from Instagram
        :return dict:  Mapped item
        """
        partial_item = node.get("_zs_partial", False)
        num_media = 1 if node["media_type"] != SearchInstagram.MEDIA_TYPE_CAROUSEL else len(node["carousel_media"])
        caption = MissingMappedField("") if "caption" not in node else "" if not node.get("caption") else node["caption"]["text"]

        # get media urls
        display_urls = []
        media_urls = []
        missing_media = None
        type_map = {SearchInstagram.MEDIA_TYPE_PHOTO: "photo", SearchInstagram.MEDIA_TYPE_VIDEO: "video"}
        media_types = set()
        # for carousels, get the first media item, for videos, get the video
        # url, for photos, get the highest resolution
        if node["media_type"] == SearchInstagram.MEDIA_TYPE_CAROUSEL:
            media_nodes = node["carousel_media"]
        else:
            media_nodes = [node]

        for media_node in media_nodes:
            if media_node["media_type"] == SearchInstagram.MEDIA_TYPE_VIDEO:
                # Get thumbnail
                if "image_versions2" in media_node:
                    display_urls.append(media_node["image_versions2"]["candidates"][0]["url"])
                elif "video_versions" in media_node:
                    # no image links at all :-/
                    # video is all we have
                    display_urls.append(media_node["video_versions"][0]["url"])
                else:
                    if partial_item:
                        # Known partial item
                        pass
                    else:
                        # New format
                        raise MapItemException("Instagram item format change")
                
                # Videos if present
                if "video_versions" in media_node:
                    media_urls.append(media_node["video_versions"][0]["url"])
                else:
                    if partial_item:
                        # Known partial item
                        pass
                    else:
                        # New format
                        raise MapItemException("Instagram item format change")

            elif media_node["media_type"] == SearchInstagram.MEDIA_TYPE_PHOTO and media_node.get("image_versions2"):
                # Images
                media_url = media_node["image_versions2"]["candidates"][0]["url"]
                display_urls.append(media_url)
                media_urls.append(media_url)
            else:
                missing_media = MissingMappedField("")

            media_types.add(type_map.get(media_node["media_type"], "unknown"))

        # type, 'mixed' means carousel with video and photo
        media_type = "mixed" if len(media_types) > 1 else media_types.pop()

        if "comment_count" in node:
            num_comments = node["comment_count"]
        elif "comments" in node and type(node["comments"]) is list:
            num_comments = len(node["comments"])
        else:
            num_comments = -1

        location = {"name": "", "latlong": "", "city": "", "location_id": ""}
        if node.get("location"):
            location["name"] = node["location"].get("name")
            location["location_id"] = node["location"].get("pk")
            location["latlong"] = str(node["location"]["lat"]) + "," + str(node["location"]["lng"]) if node[
                "location"].get("lat") else ""
            location["city"] = node["location"].get("city")

        user = node.get("user", {})
        owner = node.get("owner", {})
        if user and owner:
            if owner.get("id") == user.get("id"):
                # Same id; owner may contain less info (e.g. no full name, username, etc.), so prefer user
                pass
            elif user.get("username") != owner.get("username"):
                raise MapItemException("Unable to parse item: different user and owner")

        # Instagram posts also allow 'Collabs' with up to one co-author
        coauthors = []
        coauthor_fullnames = []
        coauthor_ids = []
        if node.get("coauthor_producers"):
            for coauthor_node in node["coauthor_producers"]:
                coauthors.append(coauthor_node.get("username", MissingMappedField("")))
                coauthor_fullnames.append(coauthor_node.get("full_name", MissingMappedField("")))
                coauthor_ids.append(coauthor_node.get("id"))
        if any([type(value) is MissingMappedField for value in coauthors]):
            coauthors = MissingMappedField("")
        else:
            coauthors = ",".join(coauthors)
        if any([type(value) is MissingMappedField for value in coauthor_fullnames]):
            coauthor_fullnames = MissingMappedField("")
        else:
            coauthor_fullnames = ",".join(coauthor_fullnames)
        

        no_likes = bool(node.get("like_and_view_counts_disabled"))

        # usertags
        if "usertags" in node:
            usertags = ",".join([user["user"]["username"] for user in node["usertags"]["in"]]) if node["usertags"] else ""
        else:
            # Not always included; MissingMappedField may be more appropriate, but it flags virtually all posts without tags (some do return `None`)
            usertags = ""
            
        if partial_item:
            # Missing data
            collected_at = MissingMappedField(0)
            unix_at = MissingMappedField(0)
            
        else:
            collected_at = datetime.datetime.fromtimestamp(node["taken_at"]).strftime("%Y-%m-%d %H:%M:%S")
            unix_at = node["taken_at"]

        mapped_item = {
            # Post and caption
            "collected_from_url": normalize_url_encoding(node.get("__import_meta", {}).get("source_platform_url")),  # Zeeschuimer metadata
            "collected_from_view": node.get("_zs_instagram_view", ""),
            "partial_item": node.get("_zs_partial", ""),
            "id": node["code"],
            "timestamp": collected_at,
            "thread_id": node["code"],
            "parent_id": node["code"],
            "url": "https://www.instagram.com/p/" + node["code"],
            "body": caption,

            # Authors
            "author_id": user.get("id", owner.get("id", MissingMappedField(""))), # This should always be present
            "author": user.get("username", owner.get("username", MissingMappedField(""))),
            "author_fullname": user.get("full_name", owner.get("full_name", MissingMappedField(""))),
            "verified": True if user.get("is_verified") else False,
            "author_avatar_url": user.get("profile_pic_url", owner.get("profile_pic_url", MissingMappedField(""))),
            "coauthors": coauthors,
            "coauthor_fullnames": coauthor_fullnames,
            "coauthor_ids": ",".join(coauthor_ids),

            # Media
            "media_type": media_type,
            "num_media": num_media,
            "image_urls": ",".join(display_urls),
            "media_urls": ",".join(media_urls),

            # Engagement
            "hashtags": ",".join(re.findall(r"#([^\s!@#$%ˆ&*()_+{}:\"|<>?\[\];'\,./`~'‘’]+)", caption)) if type(caption) is not MissingMappedField else "",
            "usertags": usertags,
            "likes_hidden": "yes" if no_likes else "no",
            "num_likes": node["like_count"] if not no_likes else MissingMappedField(0),
            "num_comments": num_comments,

            # Location
            "location_name": location["name"],
            "location_id": location["location_id"],
            "location_latlong": location["latlong"],
            "location_city": location["city"],

            # Metadata
            "unix_timestamp": unix_at,
            "missing_media": missing_media, # This denotes media that is unable to be mapped and is otherwise None
        }

        return mapped_item