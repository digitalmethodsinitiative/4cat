"""
Import scraped LinkedIn data

It's prohibitively difficult to scrape data from LinkedIn within 4CAT itself
due to its aggressive rate limiting and login wall. Instead, import data
collected elsewhere.
"""
import datetime
import time
import re

from backend.lib.search import Search


class SearchLinkedIn(Search):
    """
    Import scraped LinkedIn data
    """
    type = "linkedin-search"  # job ID
    category = "Search"  # category
    title = "Import scraped LinkedIn data"  # title displayed in UI
    description = "Import LinkedIn data collected with an external tool such as Zeeschuimer."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_from_extension = True

    # not available as a processor for existing datasets
    accepts = [None]
    references = [
        "[Zeeschuimer browser extension](https://github.com/digitalmethodsinitiative/zeeschuimer)",
        "[Worksheet: Capturing TikTok data with Zeeschuimer and 4CAT](https://tinyurl.com/nmrw-zeeschuimer-tiktok) (also explains general usage of Zeeschuimer)"
    ]

    def get_items(self, query):
        """
        Run custom search

        Not available for LinkedIn
        """
        raise NotImplementedError("LinkedIn datasets can only be created by importing data from elsewhere")

    @staticmethod
    def map_item(node):
        """
        Parse LinkedIn post in Voyager V2 format

        'Voyager V2' seems to be how the format is referred to in the data
        itself...

        :param node:  Data as received from LinkedIn
        :return dict:  Mapped item
        """

        # annoyingly, posts don't come with a timestamp
        # approximate it by using the time of collection and the "time ago"
        # included with the post (e.g. 'published 18h ago')
        post = node

        if not post.get("actor"):
            return {}

        if "__import_meta" in node:
            time_collected = int(node["__import_meta"]["timestamp_collected"] / 1000)  # milliseconds
        else:
            # best we got
            time_collected = int(time.time())

        time_ago = post["actor"]["subDescription"]["text"] if post["actor"].get("subDescription") else ""
        timestamp = int(time_collected - SearchLinkedIn.parse_time_ago(time_ago))

        # images are stored in some convoluted way
        # there are multiple URLs for various thumbnails, use the one for the
        # largest version of the image
        images = []
        if post["content"] and "images" in post["content"]:
            for image in post["content"]["images"]:
                image_data = image["attributes"][0]["vectorImage"]
                artifacts = sorted(image_data["artifacts"], key=lambda x: x["width"], reverse=True)
                url = image_data["rootUrl"] + artifacts[0]["fileIdentifyingUrlPathSegment"]
                images.append(url)

        author = SearchLinkedIn.get_author(post)

        # the ID is in the format 'urn:li:activity:6960882777168695296'
        # retain the numerical part as the item ID for 4CAT
        # sometimes posts seem to be combined, e.g.:
        # urn:li:aggregate:(urn:li:activity:3966023054712791616,urn:li:activity:3965915018238312449)
        # effectively both IDs seem to refer to the same post, so just take the
        # first one
        urn = "urn:li:activity:" + post["updateMetadata"]["urn"].split("urn:li:activity:")[1].split(",")[0].split(")")[0]
        item_id = urn.split(":").pop()

        mapped_item = {
            "id": item_id,
            "thread_id": item_id,
            "body": post["commentary"]["text"]["text"] if post["commentary"] else "",
            "timestamp": datetime.datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp_collected": datetime.datetime.utcfromtimestamp(time_collected).strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp_ago": time_ago.split("•")[0].strip(),
            "is_promoted": "yes" if not re.findall(r"[0-9]", time_ago) else "no",
            **{("author_" + k).replace("_username", ""): v for k, v in author.items()},
            "hashtags": ",".join([tag["trackingUrn"].split(":").pop() for tag in post["commentary"]["text"].get("attributes", []) if tag["type"] == "HASHTAG"]) if post["commentary"] else "",
            "image_urls": ",".join(images),
            "post_url": "https://www.linkedin.com/feed/update/" + urn,
            "link_url": post["content"]["navigationContext"].get("actionTarget", "") if (post.get("content") and post["content"].get("navigationContext")) else "",
            "likes": post["*socialDetail"]["likes"]["paging"]["total"],
            "comments": post["*socialDetail"]["comments"]["paging"]["total"],
            "shares": post["*socialDetail"]["totalShares"],
            "inclusion_context": post["header"]["text"]["text"] if post.get("header") else "",
            "unix_timestamp": timestamp,
            "unix_timestamp_collected": time_collected
        }

        return mapped_item

    @staticmethod
    def get_author(post):
        """
        Extract author information from post

        This is a bit complicated because it works differently for companies
        and users and some fields are not always present. Hence, a separate
        method.

        :param dict post:  Post data
        :return dict:  Author information
        """
        author = {
            "username": post["actor"]["navigationContext"]["actionTarget"].split("linkedin.com/").pop().split("?")[0],
            "name": post["actor"]["name"]["text"],
            "description": post["actor"].get("description", {}).get("text", ""),
            "pronouns": "",
            "avatar_url": "",
            "is_company": "no",
            "url": post["actor"]["navigationContext"]["actionTarget"].split("?")[0],
        }

        # likewise for author avatars
        if post["actor"]["name"]["attributes"]:
            if "*miniProfile" in post["actor"]["name"]["attributes"][0]:
                author_profile = post["actor"]["name"]["attributes"][0]["*miniProfile"]
                if author_profile["picture"]:
                    avatar_artifacts = sorted(author_profile["picture"]["artifacts"], key=lambda x: x["width"], reverse=True)
                    author.update({"avatar_url": author_profile["picture"]["rootUrl"] + avatar_artifacts[0]["fileIdentifyingUrlPathSegment"]})

                if author_profile.get("customPronoun"):
                    author.update({"pronouns": author_profile.get("customPronoun")})
                elif author_profile.get("standardizedPronoun"):
                    author.update({"pronouns": author_profile.get("standardizedPronoun").lower()})

            elif "*miniCompany" in post["actor"]["name"]["attributes"][0]:
                author_profile = post["actor"]["name"]["attributes"][0]["*miniCompany"]
                avatar_artifacts = sorted(author_profile["logo"]["artifacts"], key=lambda x: x["width"], reverse=True)

                author.update({"is_company": "yes"})
                author.update({"avatar_url": author_profile["logo"]["rootUrl"] + avatar_artifacts[0]["fileIdentifyingUrlPathSegment"]})

        return author

    @staticmethod
    def parse_time_ago(time_ago):
        """
        Attempt to parse a timestamp for a post

        LinkedIn doesn't give us the actual timestamp, only a relative
        indicator like "18h ago". This is annoying because it gets more
        imprecise the longer ago it is, and because it is language-sensitive.
        For example, in English 18 months is displayed as "18mo" but in Dutch
        it is "18 mnd".

        Right now this will only adjust the 'collected at' timestamp if the
        data was scraped from an English or Dutch interface, and even then the
        timestamps will still be imprecise.

        :param str time_ago:  Relative timestamp, e.g. '18mo'.
        :return int:  Estimated timestamp of post, as unix timestamp
        """
        time_ago = time_ago.split("•")[0]
        numbers = re.sub(r"[^0-9]", "", time_ago).strip()
        letters = re.sub(r"[0-9]", "", time_ago).strip()

        period_lengths = {
            "s": 1,
            "m": 60,
            "h": 3600,
            "d": 86400,
            "w": 7 * 86400,
            "mo": 30.4375 * 86400,  # we don't know WHICH months, so use the average length of a month
            "mnd": 30.4375 * 86400,
            "yr": 365.25 * 86400,  # likewise
            "j": 365.25 * 86400,
        }

        numbers = int(numbers) if len(numbers) else 0
        return period_lengths.get(letters, 0) * numbers
