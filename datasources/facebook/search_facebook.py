"""
Import scraped Facebook data

It's prohibitively difficult to scrape data from Facebook within 4CAT itself due
to its aggressive rate limiting. Instead, import data collected elsewhere.
"""

from datetime import datetime
import json

from backend.lib.search import Search
from common.lib.item_mapping import MappedItem


class SearchFacebook(Search):
    """
    Import scraped 9gag data
    """

    type = "facebook-search"  # job ID
    category = "Search"  # category
    title = "Import scraped Facebook data"  # title displayed in UI
    description = "Import Facebook data collected with an external tool such as Zeeschuimer."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_from_zeeschuimer = True

    # not available as a processor for existing datasets
    accepts = [None]
    references = [
        "[Zeeschuimer browser extension](https://github.com/digitalmethodsinitiative/zeeschuimer)",
        "[Worksheet: Capturing TikTok data with Zeeschuimer and 4CAT](https://tinyurl.com/nmrw-zeeschuimer-tiktok)",
    ]

    def get_items(self, query):
        """
        Run custom search

        Not available for 9gag
        """
        raise NotImplementedError(
            "Facebook datasets can only be created by importing data from elsewhere"
        )

    @staticmethod
    def map_item(post):
        try:
            main_data = post["comet_sections"]["content"]["story"]
        except Exception as e:
            print(json.dumps(post, indent=2))
            raise e

        # lol, get a load of this
        metadata = [
            m
            for m in post["comet_sections"]["context_layout"]["story"][
                "comet_sections"
            ]["metadata"]
            if m["__typename"] == "CometFeedStoryMinimizedTimestampStrategy"
        ].pop(0)["story"]
        post_timestamp = datetime.fromtimestamp(int(metadata["creation_time"]))

        in_group = "/groups/" in metadata["url"]
        group = ""
        if in_group:
            group = metadata["url"].split("/groups/")[1].split("/")[0]

        author = main_data["actors"][0]

        image_urls = []
        video_urls = []
        for attachment in main_data["attachments"]:
            if attachment["target"]["__typename"] == "Photo":
                image_urls.append(
                    f"https://www.facebook.com/photo/?fbid={attachment['target']['id']}"
                )

        return MappedItem(
            {
                "id": main_data["post_id"],
                "url": main_data["wwwURL"],
                "body": main_data.get("message", {}).get("text", ""),
                "timestamp": post_timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "author": author.get("url").split("/")[-1],
                "author_name": author.get("name", ""),
                "image_url": ",".join(image_urls),
                "video_url": ",".join(video_urls),
                "is_in_group": "yes" if in_group else "no",
                "group_name": group,
                "unix_timestamp": int(post_timestamp.timestamp()),
            }
        )
