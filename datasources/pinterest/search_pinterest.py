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

        Pretty simple, except posts sometimes don't have timestamps :|

        :param dict post:  Pinterest object
        :return MappedItem:  Mapped item
        """
        try:
            timestamp = datetime.strptime(post.get("created_at"), "%a, %d %b %Y %H:%M:%S %z")
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
            "author": post["pinner"]["username"],
            "author_fullname": post["pinner"].get("fullName", post["pinner"].get("full_name", "")),
            "author_original": post["nativeCreator"]["username"] if post.get("nativeCreator") else post["pinner"]["username"],
            "body": post["description"].strip(),
            "subject": post["title"].strip(),
            "ai_description": post.get("auto_alt_text", ""),
            "pinner_original": post["originPinner"]["fullName"] if post.get("originPinner") else "",
            "pinner_via": post["viaPinner"]["fullName"] if post.get("viaPinner") else "",
            "board": post["board"]["name"],
            "board_pins": post["board"].get("pinCount", post["board"].get("pin_count")),
            "board_url": f"https://www.pinterest.com{post['board']['url']}",
            "timestamp": str_timestamp,  # there are no timestamps :(
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
