"""
Import scraped Instagram data

It's prohibitively difficult to scrape data from Instagram within 4CAT itself
due to its aggressive rate limiting. Instead, import data collected elsewhere.
"""
from pathlib import Path
import json
import re

from backend.abstract.search import Search
from common.lib.helpers import UserInput
from common.lib.exceptions import WorkerInterruptedException


class SearchInstagram(Search):
    """
    Import scraped Instagram data
    """
    type = "instagram-search"  # job ID
    category = "Search"  # category
    title = "Import scraped Instagram data"  # title displayed in UI
    description = "Import Instagram data collected with an external tool such as Zeeschuimer."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI
    is_local = False    # Whether this datasource is locally scraped
    is_static = False   # Whether this datasource is still updated

    # not available as a processor for existing datasets
    accepts = [None]

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

    def import_from_file(self, path):
        """
        Import items from an external file

        By default, this reads a file and parses each line as JSON, returning
        the parsed object as an item. This works for NDJSON files. Data sources
        that require importing from other or multiple file types can overwrite
        this method.

        The file is considered disposable and deleted after importing.

        Instagram importing is a little bit roundabout since we can expect
        input in two separate and not completely overlapping formats - an "edge
        list" or an "item list", and posts are structured differently between
        those, and do not contain the same data. So we find a middle ground
        here... each format has its own handler function

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

                post = json.loads(line)
                node = post["data"]
                is_graph_response = "__typename" in node

                if is_graph_response:
                    yield self.parse_graph_item(node)
                else:
                    yield self.parse_itemlist_item(node)

        path.unlink()

    def parse_graph_item(self, node):
        """
        Parse Instagram post in Graph format

        :param node:  Data as received from Instagram
        :return dict:  Mapped item
        """
        try:
            caption = node["edge_media_to_caption"]["edges"][0]["node"]["text"]
        except IndexError:
            caption = ""

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
            print(json.dumps(media_node))
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

        mapped_item = {
            "id": node["shortcode"],
            "thread_id": node["shortcode"],
            "parent_id": node["shortcode"],
            "body": caption,
            "author": node["owner"]["username"],
            "author_fullname": node["owner"].get("full_name", ""),
            "author_avatar_url": node["owner"].get("profile_pic_url", ""),
            "timestamp": node["taken_at_timestamp"],
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
            "subject": ""
        }

        return mapped_item

    def parse_itemlist_item(self, node):
        """
        Parse Instagram post in 'item list' format

        :param node:  Data as received from Instagram
        :return dict:  Mapped item
        """
        num_media = 1 if node["media_type"] != self.MEDIA_TYPE_CAROUSEL else len(node["carousel_media"])
        caption = "" if not node.get("caption") else node["caption"]["text"]

        # get media url
        # for carousels, get the first media item, for videos, get the video
        # url, for photos, get the highest resolution
        if node["media_type"] == self.MEDIA_TYPE_CAROUSEL:
            media_node = node["carousel_media"][0]
        else:
            media_node = node

        if media_node["media_type"] == self.MEDIA_TYPE_VIDEO:
            media_url = media_node["video_versions"][0]["url"]
            display_url = media_node["image_versions2"]["candidates"][0]["url"]
        elif media_node["media_type"] == self.MEDIA_TYPE_PHOTO:
            media_url = media_node["image_versions2"]["candidates"][0]["url"]
            display_url = media_url
        else:
            media_url = ""
            display_url = ""

        # type, 'mixed' means carousel with video and photo
        type_map = {self.MEDIA_TYPE_PHOTO: "photo", self.MEDIA_TYPE_VIDEO: "video"}
        if node["media_type"] != self.MEDIA_TYPE_CAROUSEL:
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

        mapped_item = {
            "id": node["code"],
            "thread_id": node["code"],
            "parent_id": node["code"],
            "body": caption,
            "author": node["user"]["username"],
            "author_fullname": node["user"]["full_name"],
            "author_avatar_url": node["user"]["profile_pic_url"],
            "timestamp": node["taken_at"],
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
            "subject": ""
        }

        return mapped_item
