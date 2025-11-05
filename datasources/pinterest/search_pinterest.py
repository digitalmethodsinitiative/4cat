"""
Import scraped Pinterest data

It's prohibitively difficult to scrape data from Pinterest within 4CAT itself due
to its aggressive rate limiting. Instead, import data collected elsewhere.
"""
from datetime import datetime

from backend.lib.search import Search
from common.lib.item_mapping import MappedItem, MissingMappedField


class SearchPinterest(Search):
    """
    Import scraped Pinterest data
    """
    type = "pinterest-search"  # job ID
    category = "Search"  # category
    title = "Import scraped Pinterest data"  # title displayed in UI
    description = "Import Pinterest data collected with an external tool such as Zeeschuimer."  # description displayed in UI
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

        Not available for Pinterest
        """
        raise NotImplementedError("Pinterest datasets can only be created by importing data from elsewhere")

    @staticmethod
    def map_item(post):
        """
        Map Pinterest object to 4CAT item

        Depending on whether the object was captured from JSON or HTML, treat it
        differently. A lot of data is missing from HTML objects.

        :param post:
        :return:
        """
        if post.get("_zs-origin") == "html":
            return SearchPinterest.map_item_from_html(post)
        else:
            return SearchPinterest.map_item_from_json(post)

    @staticmethod
    def map_item_from_json(post):
        """
        Map Pinterest object to 4CAT item

        Pretty simple, except posts sometimes don't have timestamps :| but at
        least these objects are more complete than the HTML data usually

        :param dict post:  Pinterest object
        :return MappedItem:  Mapped item
        """
        try:
            # there are often no timestamps :'(
            timestamp = datetime.strptime(post.get("created_at", post.get("createdAt")), "%a, %d %b %Y %H:%M:%S %z")
            unix_timestamp = int(timestamp.timestamp())
            str_timestamp = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            unix_timestamp = str_timestamp = MissingMappedField("")

        post_id = post.get("entityId", post["id"])

        if "imageSpec_orig" in post:
            image_url = post["imageSpec_orig"]["url"]
        else:
            image_url = post["images"]["orig"]["url"]

        return MappedItem({
            "id": post_id,
            "thread_id": post_id,
            "author": post["pinner"]["username"],
            "author_fullname": post["pinner"].get("fullName", post["pinner"].get("full_name", "")),
            "author_original": post["nativeCreator"]["username"] if post.get("nativeCreator") else post["pinner"]["username"],
            "body": post.get("description", "").strip(),
            "subject": post["title"].strip(),
            "ai_description": post.get("auto_alt_text", ""),
            "pinner_original": post["originPinner"]["fullName"] if post.get("originPinner") else "",
            "pinner_via": post["viaPinner"]["fullName"] if post.get("viaPinner") else "",
            "board": post["board"]["name"],
            "board_pins": post["board"].get("pinCount", post["board"].get("pin_count")),
            "board_url": f"https://www.pinterest.com{post['board']['url']}",
            "timestamp": str_timestamp,
            "idea_tags": ",".join(post["pinJoin"]["visualAnnotation"]) if post.get("pinJoin") else "",
            "url": f"https://www.pinterest.com/pin/{post_id}",
            # these are not always available (shame)
            # "is_repin": "yes" if post["isRepin"] else "no",
            # "is_unsafe": "yes" if post["isUnsafe"] else "no",
            # "total_saves": post["aggregatedPinData"]["aggregatedStats"]["saves"],
            "is_video": "yes" if post.get("isVideo", post.get("videos")) else "no",
            "image_url": image_url,
            "dominant_colour": post.get("dominantColor", post.get("dominant_color")),
            "unix_timestamp": unix_timestamp
        })

    @staticmethod
    def map_item_from_html(post):
        """
        Map Pinterest object to 4CAT item

        These are from the HTML and have even less data than JSON objects...
        but enough to be useful in some cases.

        :param dict post:  Pinterest object
        :return MappedItem:  Mapped item
        """
        return MappedItem({
            "id": int(post["id"]),
            "thread_id": int(post["id"]),
            "author": MissingMappedField(""),
            "author_fullname": MissingMappedField(""),
            "author_original": MissingMappedField(""),
            "body": post["body"].strip(),
            "subject": post["title"].strip(),
            "ai_description": MissingMappedField(""),
            "pinner_original": MissingMappedField(""),
            "pinner_via": MissingMappedField(""),
            "board": MissingMappedField(""),
            "board_pins": MissingMappedField(""),
            "board_url": MissingMappedField(""),
            "timestamp": MissingMappedField(""),  # there are no timestamps :(
            "idea_tags": ",".join(post["tags"]),
            "url": f"https://www.pinterest.com/pin/{post['id']}",
            # these are not always available (shame)
            # "is_repin": "yes" if post["isRepin"] else "no",
            # "is_unsafe": "yes" if post["isUnsafe"] else "no",
            # "total_saves": post["aggregatedPinData"]["aggregatedStats"]["saves"],
            "is_video": MissingMappedField(""),
            "image_url": post["image"],
            "dominant_colour": MissingMappedField(""),
            "unix_timestamp": MissingMappedField("")
        })
