"""
Import scraped 9gag data

It's prohibitively difficult to scrape data from 9gag within 4CAT itself due
to its aggressive rate limiting. Instead, import data collected elsewhere.
"""
from datetime import datetime

from backend.lib.search import Search


class SearchNineGag(Search):
    """
    Import scraped 9gag data
    """
    type = "ninegag-search"  # job ID
    category = "Search"  # category
    title = "Import scraped 9gag data"  # title displayed in UI
    description = "Import 9gag data collected with an external tool such as Zeeschuimer."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_from_extension = True

    # not available as a processor for existing datasets
    accepts = [None]
    references = [
        "[Zeeschuimer browser extension](https://github.com/digitalmethodsinitiative/zeeschuimer)",
        "[Worksheet: Capturing TikTok data with Zeeschuimer and 4CAT](https://tinyurl.com/nmrw-zeeschuimer-tiktok)"
    ]

    def get_items(self, query):
        """
        Run custom search

        Not available for 9gag
        """
        raise NotImplementedError("9gag datasets can only be created by importing data from elsewhere")

    @staticmethod
    def map_item(post):
        post_timestamp = datetime.fromtimestamp(post["creationTs"])

        image = sorted([v for v in post["images"].values() if not "hasAudio" in v], key=lambda image: image["width"] * image["height"], reverse=True)[0]
        video = sorted([v for v in post["images"].values() if "hasAudio" in v], key=lambda image: image["width"] * image["height"], reverse=True)

        video_url = ""
        if video:
            # annoyingly, not all formats are always available
            video = video[0]
            if "av1Url" in video:
                video_url = video["av1Url"]
            elif "h265Url" in video:
                video_url = video["h265Url"]
            elif "vp9Url" in video:
                video_url = video["vp9Url"]
            elif "vp8Url" in video:
                video_url = video["vp8Url"]

        if not post["creator"]:
            # anonymous posts exist
            # they display as from the user '9GAGGER' on the website
            post["creator"] = {
                "username": "9GAGGER",
                "fullName": "",
                "emojiStatus": "",
                "isVerifiedAccount": ""
            }

        return {
            "id": post["id"],
            "url": post["url"],
            "subject": post["title"],
            "body": post["description"],
            "timestamp": post_timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "author": post["creator"]["username"],
            "author_name": post["creator"]["fullName"],
            "author_status": post["creator"]["emojiStatus"],
            "author_verified": "yes" if post["creator"]["isVerifiedAccount"] else "no",
            "type": post["type"],
            "image_url": image["url"],
            "video_url": video_url,
            "is_nsfw": "no" if post["nsfw"] == 0 else "yes",
            "is_promoted": "no" if post["promoted"] == 0 else "yes",
            "is_vote_masked": "no" if post["isVoteMasked"] == 0 else "yes",
            "is_anonymous": "no" if not post["isAnonymous"] else "yes",
            "source_domain": post["sourceDomain"],
            "source_url": post["sourceUrl"],
            "upvotes": post["upVoteCount"],
            "downvotes": post["downVoteCount"],
            "score": post["upVoteCount"] - post["downVoteCount"],
            "comments": post["commentsCount"],
            "tags": ",".join([tag["key"] for tag in post["tags"]]),
            "tags_annotated": ",".join(post["annotationTags"]),
            "unix_timestamp": int(post_timestamp.timestamp()),
        }
