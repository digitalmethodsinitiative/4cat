"""
Import scraped Instagram data

It's prohibitively difficult to scrape data from Instagram within 4CAT itself
due to its aggressive rate limiting. Instead, import data collected elsewhere.
"""
import datetime
import re

from backend.lib.search import Search
from common.lib.item_mapping import MappedItem, MissingMappedField, value_or_missing
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

    HASHTAG_REGEX = re.compile(r"#([^\s!@#$%ˆ&*()_+{}:\"|<>?\[\];'\,./`~'‘’]+)")

    @staticmethod
    def extract_hashtags(caption):
        """
        Extract comma-joined hashtags from a caption, tolerating MissingMappedField.
        """
        if isinstance(caption, MissingMappedField):
            return ""
        return ",".join(SearchInstagram.HASHTAG_REGEX.findall(caption))

    @staticmethod
    def get_author(node):
        """
        Collect the details of the account that posted an item

        Instagram puts these under 'user', under 'owner', or spread over both,
        and either of the two may be present but empty. Combine them into one
        dictionary, preferring 'user' wherever both hold a value.

        :param dict node:  Data as received from Instagram
        :return dict:  Author details; empty if the item has none at all
        """
        user = node.get("user") or {}
        owner = node.get("owner") or {}

        # Only a disagreement between two known usernames means the item holds
        # two different accounts. 'owner' is often just an ID, and in
        # pseudonymised datasets only the 'user' details are replaced by
        # hashes, so comparing IDs would reject perfectly good items.
        if user.get("username") and owner.get("username") and user["username"] != owner["username"]:
            raise MapItemException("Unable to parse item: different user and owner")

        author = {**owner}
        author.update({key: value for key, value in user.items() if value is not None})
        return author

    @staticmethod
    def get_author_id(node, author):
        """
        Find the numerical ID of the account that posted an item

        Grid and thumbnail views often leave the author details out entirely.
        An item's own ID is built as '<item ID>_<author ID>' though, so the
        second half can stand in for the missing value.

        :param dict node:  Data as received from Instagram
        :param dict author:  Author details, as returned by get_author()
        :return:  Author ID, or a MissingMappedField if the item has none
        """
        author_id = author.get("id") or author.get("pk")
        if author_id:
            return author_id

        item_id = node.get("id")
        if isinstance(item_id, str) and "_" in item_id:
            return item_id.split("_")[1]

        return MissingMappedField("")

    @staticmethod
    def get_value_or_missing(node, key, default):
        """
        Read a field from Instagram data, marking it missing if there is no value

        Instagram leaves a field out of a response, or sends it as null, for
        the same reason: the page the post was captured from does not carry
        that detail. So for the fields read through here, both count as
        missing.

        This does not hold for every field. A null caption, location or
        carousel means the post genuinely has none of that, and those are
        mapped to an empty value where they are read rather than through here.
        A field can also hold a value that is present, not null, and still
        untrue - Instagram reports a handful of likes on posts whose like count
        is hidden - which no lookup can detect and which is dealt with at the
        field itself.

        :param dict node:  Data as received from Instagram
        :param str key:  Name of the field to read
        :param default:  Value processors should fall back on if the field is
          missing
        :return:  The field's value, or a MissingMappedField
        """
        value = value_or_missing(node, key, default)
        return MissingMappedField(default) if value is None else value

    @staticmethod
    def get_image_url(candidates):
        """
        Get the link to Instagram's own first choice of image

        Instagram offers each image at a number of sizes and crops. The first
        one listed is the largest version that still shows the whole image;
        larger ones further down the list are square crops of it, so those are
        not a better choice even though they have more pixels.

        :param candidates:  List of image versions, as received from Instagram
        :return str:  Link to the image, or an empty string if there is none
        """
        if not isinstance(candidates, list):
            return ""

        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("url"):
                return candidate["url"]

        return ""

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
        input in a number of separate and not completely overlapping formats,
        and posts are structured differently between those, and do not contain
        the same data. So we find a middle ground here... each format has its
        own handler function.

        On top of that, the same format holds different amounts of data
        depending on the page it was captured from: grid and thumbnail views
        leave out the post date, the author details, and the video links. Such
        items are mapped as far as they go, with the values that are not there
        marked as missing.

        :param dict item:  Item to map
        :return:  Mapped item
        """
        link = item.get("link", "")
        if (item.get("product_type", "") == "ad") or \
                (link and link.startswith("https://www.facebook.com/ads/ig_redirect")):
            # These are ads
            raise MapItemException("appears to be Instagram ad, check raw data to confirm and ensure Zeeschuimer is up to date.")

        # Only the older website format announces itself by name ('GraphImage',
        # 'GraphVideo', 'GraphSidecar'). Anything else resembles the item list
        # format most closely, so send unrecognised names there rather than to a
        # parser that would look for keys they do not have.
        typename = item.get("__typename") or ""

        if "polaris" in typename.lower():
            return MappedItem(SearchInstagram.parse_polaris_item(item))
        elif typename.startswith("Graph"):
            return MappedItem(SearchInstagram.parse_graph_item(item))
        else:
            return MappedItem(SearchInstagram.parse_itemlist_item(item))

    @staticmethod
    def parse_polaris_item(node):
        """
        Parse Instagram post in Polaris format

        2026-2-24 Appears standard format; no noted variable keys in test examples.

        :param node:  Data as received from Instagram
        :return dict:  Mapped item
        """
        # 2026-2-24 Polaris format appears throughout as grid format, but contains partial data
        partial_item = node.get("_zs_partial", False)
        collected_at = MissingMappedField(0)
        unix_at = MissingMappedField(0)
        # 2026-2-24 node["caption"]["text"] 
        caption = MissingMappedField("") if "caption" not in node else "" if not node.get("caption") else node["caption"]["text"]
        

        author = SearchInstagram.get_author(node)
        # in pseudonymised datasets this is a hash rather than a yes/no, so read
        # it as "there is a value" and only call it missing when there is none
        is_verified = MissingMappedField(False) if author.get("is_verified") is None else bool(author["is_verified"])

        # media type
        # 2026-2-14 XIGPolarisCarouselMedia and XIGPolarisPhotoMedia not actually seen
        type_map = {"XIGPolarisPhotoMedia": "photo", "XIGPolarisVideoMedia": "video"}
        media_type = type_map.get(node["__typename"], "unknown")
        # maybe similar to old graph?
        num_media = 1 if node["__typename"] != "XIGPolarisCarouselMedia" else len(node.get("carousel_media") or [])

        # get media urls
        display_urls = SearchInstagram.get_value_or_missing(node, "display_uri", "")
        missing_media = None
        video_versions = node.get("video_versions") or []
        if video_versions and type(video_versions[0]) is dict:
            media_urls = SearchInstagram.get_value_or_missing(video_versions[0], "url", "")
        else:
            media_urls = MissingMappedField("")
        
        mapped_item = {
            # Post and caption
            "collected_from_url": normalize_url_encoding(node.get("__import_meta", {}).get("source_platform_url")),  # Zeeschuimer metadata
            "collected_from_view": node.get("_zs_instagram_view", ""),
            "partial_item": partial_item,
            "id": node["code"],
            "timestamp": collected_at,
            "thread_id": node["code"],
            "parent_id": node["code"],
            "url": "https://www.instagram.com/p/" + node["code"],
            "body": caption,

            # Authors
            "author_id": SearchInstagram.get_author_id(node, author),
            "author": SearchInstagram.get_value_or_missing(author, "username", ""),
            # full_name not seen in this format
            "author_fullname": SearchInstagram.get_value_or_missing(author, "full_name", ""),
            "verified": is_verified,
            "author_avatar_url": SearchInstagram.get_value_or_missing(author, "profile_pic_url", ""),

             # Not available in this format
            "coauthors": MissingMappedField(""),
            "coauthor_fullnames": MissingMappedField(""),
            "coauthor_ids": MissingMappedField(""),
            
            # Media
            "media_type": media_type,
            "num_media": num_media,
            "image_urls": display_urls,
            "media_urls": media_urls,

            # Engagement
            "hashtags": SearchInstagram.extract_hashtags(caption),
            "usertags": MissingMappedField(""), # Not available in this format
            "play_count": SearchInstagram.get_value_or_missing(node, "play_count", -1),
            
            "likes_hidden": MissingMappedField(""), # Not available in this format
            "num_likes": MissingMappedField(-1),
            "num_comments": MissingMappedField(-1),

            # Location not available (even for location tags)
            "location_name": MissingMappedField(""),
            "location_id": MissingMappedField(""),
            "location_latlong": MissingMappedField(""),
            "location_city": MissingMappedField(""),

            # Metadata
            "unix_timestamp": unix_at,
            "missing_media": missing_media, # This denotes media that is unable to be mapped and is otherwise None
        }

        return mapped_item

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

        author = SearchInstagram.get_author(node)

        # 2026-2-24 play_count/view_count only seen in Polaris format at this time with data (view_count exists here by is None; play_count not present at all)
        if node.get("view_count") is not None:
            play_count = node["view_count"]
        elif node.get("play_count") is not None:
            play_count = node["play_count"]
        else:            
            play_count = MissingMappedField(-1)

        mapped_item = {
            # Post data
            "id": node["shortcode"],
            "collected_from_url": normalize_url_encoding(node.get("__import_meta", {}).get("source_platform_url", "")),  # Zeeschuimer metadata
            "collected_from_view": SearchInstagram.get_value_or_missing(node, "_zs_instagram_view", ""),
            "partial_item": SearchInstagram.get_value_or_missing(node, "_zs_partial", ""),
            "timestamp": datetime.datetime.fromtimestamp(node["taken_at_timestamp"]).strftime("%Y-%m-%d %H:%M:%S"),
            "thread_id": node["shortcode"],
            "parent_id": node["shortcode"],
            "url": "https://www.instagram.com/p/" + node["shortcode"],
            "body": caption,


            # Author data
            "author_id": SearchInstagram.get_author_id(node, author),
            "author": SearchInstagram.get_value_or_missing(author, "username", ""),
            "author_fullname": SearchInstagram.get_value_or_missing(author, "full_name", ""),
            "verified": True if author.get("is_verified") else False,
            "author_avatar_url": SearchInstagram.get_value_or_missing(author, "profile_pic_url", ""),
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
            "hashtags": SearchInstagram.extract_hashtags(caption),
            # Unsure if usertags will work; need data (this could raise it to attention...)
            "usertags": ",".join(
                [tagged["node"]["user"]["username"]
                 for tagged in (node.get("edge_media_to_tagged_user") or {}).get("edges") or []]),
            "play_count": play_count,
            "likes_hidden": "yes" if no_likes else "no",
            "num_likes": SearchInstagram.get_value_or_missing(node.get("edge_media_preview_like") or {}, "count", -1) if not no_likes else MissingMappedField(-1),
            "num_comments": SearchInstagram.get_value_or_missing(node.get("edge_media_preview_comment") or {}, "count", -1),

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

        The same format holds different amounts of data depending on which page
        the post was captured from. Grid and thumbnail views in particular leave
        out the post date, the author details and the video links. Those posts
        are still mapped, with the values that are not there marked as missing,
        rather than skipped altogether.

        :param node:  Data as received from Instagram
        :return dict:  Mapped item
        """
        code = node.get("code")
        if not code:
            raise MapItemException("Unable to parse item: no post code to identify the post by")

        caption = MissingMappedField("") if "caption" not in node else "" if not node.get("caption") else node["caption"]["text"]

        # get media urls
        display_urls = []
        media_urls = []
        missing_media = None
        type_map = {SearchInstagram.MEDIA_TYPE_PHOTO: "photo", SearchInstagram.MEDIA_TYPE_VIDEO: "video"}
        media_types = set()

        # for carousels, go through every item in the carousel; for videos, get
        # the video url; for photos, get the image
        carousel_media = node.get("carousel_media") or []
        if node.get("media_type") == SearchInstagram.MEDIA_TYPE_CAROUSEL:
            # some pages say how many items a carousel holds without including
            # the items themselves
            num_media = len(carousel_media) or node.get("carousel_media_count") or 1
        else:
            num_media = 1
        media_nodes = carousel_media if carousel_media else [node]

        for media_node in media_nodes:
            thumbnail_url = SearchInstagram.get_image_url((media_node.get("image_versions2") or {}).get("candidates"))
            video_versions = media_node.get("video_versions") or []
            video_url = video_versions[0].get("url", "") if video_versions and type(video_versions[0]) is dict else ""

            media_node_type = media_node.get("media_type")
            if media_node_type == SearchInstagram.MEDIA_TYPE_VIDEO:
                if thumbnail_url:
                    display_urls.append(thumbnail_url)
                elif video_url:
                    # no image links at all :-/
                    # video is all we have
                    display_urls.append(video_url)

                if video_url:
                    media_urls.append(video_url)
                else:
                    # only the video link is missing, not the post itself, so
                    # keep the post and record that its media could not be mapped
                    missing_media = MissingMappedField("")

            elif media_node_type == SearchInstagram.MEDIA_TYPE_PHOTO and thumbnail_url:
                display_urls.append(thumbnail_url)
                media_urls.append(thumbnail_url)

            else:
                missing_media = MissingMappedField("")

            media_types.add(type_map.get(media_node_type, "unknown"))

        # type, 'mixed' means carousel with video and photo
        media_type = "mixed" if len(media_types) > 1 else media_types.pop()

        if node.get("comment_count") is not None:
            num_comments = node["comment_count"]
        elif type(node.get("comments")) is list:
            num_comments = len(node["comments"])
        else:
            num_comments = MissingMappedField(-1)

        location = {"name": "", "latlong": "", "city": "", "location_id": ""}
        if node.get("location"):
            location["name"] = node["location"].get("name") or ""
            location["location_id"] = node["location"].get("pk") or ""
            location["latlong"] = str(node["location"]["lat"]) + "," + str(node["location"]["lng"]) if node[
                "location"].get("lat") else ""
            location["city"] = node["location"].get("city") or ""

        author = SearchInstagram.get_author(node)
        # in pseudonymised datasets this is a hash rather than a yes/no, so read
        # it as "there is a value" and only call it missing when there is none
        is_verified = MissingMappedField(False) if author.get("is_verified") is None else bool(author["is_verified"])

        # Instagram posts also allow 'Collabs' with up to one co-author
        coauthors = []
        coauthor_fullnames = []
        coauthor_ids = []
        if node.get("coauthor_producers"):
            for coauthor_node in node["coauthor_producers"]:
                coauthors.append(coauthor_node.get("username") or "")
                coauthor_fullnames.append(coauthor_node.get("full_name") or "")
                coauthor_ids.append(coauthor_node.get("id") or "")
        coauthors = ",".join(coauthors) if any(coauthors) else ""
        coauthor_fullnames = ",".join(coauthor_fullnames) if any(coauthor_fullnames) else ""
        coauthor_ids = ",".join(coauthor_ids) if any(coauthor_ids) else ""

        no_likes = bool(node.get("like_and_view_counts_disabled"))
        # Instagram reports a small, made-up like count on posts whose likes are
        # hidden, so the flag is the only way to know the number is not real
        num_likes = MissingMappedField(-1) if no_likes or node.get("like_count") is None else node["like_count"]

        # 2026-2-24 play_count/view_count only seen in Polaris format at this time with data (view_count exists here by is None; play_count not present at all)
        if node.get("view_count") is not None:
            play_count = node["view_count"]
        elif node.get("play_count") is not None:
            play_count = node["play_count"]
        else:
            play_count = MissingMappedField(-1)

        # usertags
        if "usertags" in node:
            usertags = ",".join([tagged["user"]["username"] for tagged in (node["usertags"] or {}).get("in") or []
                                 if type(tagged.get("user")) is dict and tagged["user"].get("username")])
        else:
            # Not always included; MissingMappedField may be more appropriate, but it flags virtually all posts without tags (some do return `None`)
            usertags = ""

        if node.get("taken_at"):
            collected_at = datetime.datetime.fromtimestamp(node["taken_at"]).strftime("%Y-%m-%d %H:%M:%S")
            unix_at = node["taken_at"]
        else:
            # grid and thumbnail views leave the post date out
            collected_at = MissingMappedField(0)
            unix_at = MissingMappedField(0)

        mapped_item = {
            # Post and caption
            "collected_from_url": normalize_url_encoding(node.get("__import_meta", {}).get("source_platform_url", "")),  # Zeeschuimer metadata
            "collected_from_view": node.get("_zs_instagram_view", ""),
            "partial_item": node.get("_zs_partial", ""),
            "id": code,
            "timestamp": collected_at,
            "thread_id": code,
            "parent_id": code,
            "url": "https://www.instagram.com/p/" + code,
            "body": caption,

            # Authors
            "author_id": SearchInstagram.get_author_id(node, author), # This should always be present
            "author": SearchInstagram.get_value_or_missing(author, "username", ""),
            "author_fullname": SearchInstagram.get_value_or_missing(author, "full_name", ""),
            "verified": is_verified,
            "author_avatar_url": SearchInstagram.get_value_or_missing(author, "profile_pic_url", ""),
            "coauthors": coauthors,
            "coauthor_fullnames": coauthor_fullnames,
            "coauthor_ids": coauthor_ids,

            # Media
            "media_type": media_type,
            "num_media": num_media,
            "image_urls": ",".join(display_urls),
            "media_urls": ",".join(media_urls),

            # Engagement
            "hashtags": SearchInstagram.extract_hashtags(caption),
            "usertags": usertags,
            "play_count": play_count,
            "likes_hidden": "yes" if no_likes else "no",
            "num_likes": num_likes,
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
