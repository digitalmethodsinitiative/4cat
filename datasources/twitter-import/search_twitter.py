"""
Import scraped X/Twitter data

It's prohibitively difficult to scrape data from Twitter within 4CAT itself due
to its aggressive rate limiting. Instead, import data collected elsewhere.
"""
from datetime import datetime

from backend.lib.search import Search
from common.lib.helpers import strip_tags
from common.lib.item_mapping import MappedItem


class SearchTwitterViaZeeschuimer(Search):
    """
    Import scraped X/Twitter data
    """
    type = "twitter-import"  # job ID
    category = "Search"  # category
    title = "Import scraped X/Twitter data"  # title displayed in UI
    description = "Import X/Twitter data collected with an external tool such as Zeeschuimer."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_from_zeeschuimer = True

    # not available as a processor for existing datasets
    accepts = []
    references = [
        "[Zeeschuimer browser extension](https://github.com/digitalmethodsinitiative/zeeschuimer)",
        "[Worksheet: Capturing TikTok data with Zeeschuimer and 4CAT](https://tinyurl.com/nmrw-zeeschuimer-tiktok)"
    ]
    
    def get_items(self, query):
        """
        Run custom search

        Not available for Twitter
        """
        raise NotImplementedError("Twitter datasets can only be created by importing data from elsewhere")

    @staticmethod
    def map_item(item):

        if item.get("rest_id"):
            return MappedItem(SearchTwitterViaZeeschuimer.map_item_modern(item))
        elif item.get("type") == "adaptive":
            return MappedItem(SearchTwitterViaZeeschuimer.map_item_legacy(item))
        else:
            raise NotImplementedError

    @staticmethod
    def map_item_modern(tweet):

        # Sometimes a "core" key appears in user_results, sometimes not.
        # This has effect on where to get user data.
        has_core = tweet.get("core", {}).get("user_results", {}).get("result", {}).get("core", False)
        user_key = "core" if has_core else "legacy"

        timestamp = datetime.strptime(tweet["legacy"]["created_at"], "%a %b %d %H:%M:%S %z %Y")
        withheld = False

        retweet = tweet["legacy"].get("retweeted_status_result")
        if retweet:
            # make sure the full RT is included, by default this is shortened
            if "tweet" in retweet["result"]:
                retweet["result"] = retweet["result"]["tweet"]

            if retweet["result"].get("legacy", {}).get("withheld_scope"):
                withheld = True
                tweet["legacy"]["full_text"] = retweet["result"]["legacy"]["full_text"]
            else:
                t_text = "RT @" + retweet["result"]["core"]["user_results"]["result"][user_key]["screen_name"] + \
                      ": " + retweet["result"]["legacy"]["full_text"]
                tweet["legacy"]["full_text"] = t_text

        quote_tweet = tweet.get("quoted_status_result")
        if quote_tweet and "tweet" in quote_tweet.get("result", {}):
            # sometimes this is one level deeper, sometimes not...
            quote_tweet["result"] = quote_tweet["result"]["tweet"]
        # check if the quote tweet is available or not
        quote_withheld = True if (quote_tweet and "tombstone" in quote_tweet["result"]) else False

        return {
            "id": tweet["rest_id"],
            "thread_id": tweet["legacy"]["conversation_id_str"],
            "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "unix_timestamp": int(timestamp.timestamp()),
            "link": f"https://x.com/{tweet['core']['user_results']['result'][user_key]['screen_name']}/status/{tweet['id']}",
            "body": tweet["legacy"]["full_text"],
            "author": tweet["core"]["user_results"]["result"][user_key]["screen_name"],
            "author_fullname": tweet["core"]["user_results"]["result"][user_key]["name"],
            "author_id": tweet["legacy"]["user_id_str"],
            "author_avatar_url": tweet["core"]["user_results"]["result"]["avatar"]["image_url"] if "avatar" in tweet["core"]["user_results"]["result"] else tweet["core"]["user_results"]["result"]["legacy"].get("profile_image_url_https", ""),
            "author_banner_url": tweet["core"]["user_results"]["result"]["legacy"].get("profile_banner_url", ""), # key does not exist when author does not have a banner
            "verified": tweet["core"]["user_results"]["result"].get("is_blue_verified", ""),
            "source": strip_tags(tweet["source"]),
            "language_guess": tweet["legacy"].get("lang"),
            "possibly_sensitive": "yes" if tweet.get("possibly_sensitive", False) or tweet["legacy"].get("possibly_sensitive", False) else "no",
            "retweet_count": tweet["legacy"]["retweet_count"],
            "reply_count": tweet["legacy"]["reply_count"],
            "like_count": tweet["legacy"]["favorite_count"],
            "quote_count": tweet["legacy"]["quote_count"],
            "impression_count": tweet.get("views", {}).get("count", ""),
            "is_retweet": "yes" if retweet else "no",
            "retweeted_user": retweet["result"]["core"]["user_results"]["result"].get("legacy", {}).get("screen_name", "") if retweet else "",
            "is_quote_tweet": "yes" if quote_tweet else "no",
            "quote_tweet_id": quote_tweet["result"].get("rest_id", "") if quote_tweet else "",
            "quote_author": quote_tweet["result"]["core"]["user_results"]["result"].get(user_key, {}).get("screen_name", "") if
                        (quote_tweet and not quote_withheld) else "",
            "quote_body": quote_tweet["result"]["legacy"].get("full_text", "") if quote_tweet and not quote_withheld else "",
            "quote_images": ",".join(
                [media["media_url_https"] for media in quote_tweet["result"]["legacy"].get("entities", {}).get("media", [])
                 if media["type"] == "photo"]) if quote_tweet and not quote_withheld else "",
            "quote_videos": ",".join(
                [media["media_url_https"] for media in quote_tweet["result"]["legacy"].get("entities", {}).get("media", [])
                 if media["type"] == "video"]) if quote_tweet and not quote_withheld else "",
            "is_quote_withheld": "yes" if quote_withheld else "no",
            "is_reply": "yes" if str(tweet["legacy"]["conversation_id_str"]) != str(tweet["rest_id"]) else "no",
            "replied_author": tweet["legacy"].get("in_reply_to_screen_name", ""),
            "is_withheld": "yes" if withheld else "no",
            "hashtags": ",".join([hashtag["text"] for hashtag in tweet["legacy"]["entities"]["hashtags"]]),
            "urls": ",".join([url.get("expanded_url", url["display_url"]) for url in tweet["legacy"]["entities"]["urls"]]),
            "images": ",".join([media["media_url_https"] for media in tweet["legacy"]["entities"].get("media", []) if
                                media["type"] == "photo"]),
            "videos": ",".join([media["media_url_https"] for media in tweet["legacy"]["entities"].get("media", []) if
                                media["type"] == "video"]),
            "mentions": ",".join([media["screen_name"] for media in tweet["legacy"]["entities"]["user_mentions"]]),
            "long_lat": SearchTwitterViaZeeschuimer.get_centroid(
                tweet["legacy"]["place"]["bounding_box"]["coordinates"]) if tweet["legacy"].get("place") else "",
            "place_name": tweet["legacy"].get("place", {}).get("full_name", "") if tweet["legacy"].get("place") else "",
        }

    @staticmethod
    def map_item_legacy(tweet):
        timestamp = datetime.strptime(tweet["legacy"]["created_at"], "%a %b %d %H:%M:%S %z %Y")
        tweet_id = tweet["legacy"]["id_str"]
        withheld = False

        retweet = tweet["legacy"].get("retweeted_status_result")
        if retweet:
            # make sure the full RT is included, by default this is shortened
            if retweet["result"].get("legacy", {}).get("withheld_status"):
                withheld = True
                tweet["legacy"]["full_text"] = retweet["result"]["legacy"]["full_text"]
            else:
                t_text = "RT @" + retweet["result"]["core"]["user_results"]["result"]["legacy"]["screen_name"] + \
                     " " + retweet["result"]["legacy"]["full_text"]
                tweet["legacy"]["full_text"] = t_text

        quote_tweet = tweet.get("quoted_status_result")

        if quote_tweet and "tweet" in quote_tweet.get("result", {}):
            # sometimes this is one level deeper, sometimes not...
            quote_tweet["result"] = quote_tweet["result"]["tweet"]

        return {
            "id": tweet_id,
            "thread_id": tweet["legacy"]["conversation_id_str"],
            "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "unix_timestamp": int(timestamp.timestamp()),
            "link": f"https://x.com/{tweet['user']['screen_name']}/status/{tweet_id}",
            "body": tweet["legacy"]["full_text"],
            "author": tweet["user"]["screen_name"],
            "author_fullname": tweet["user"]["name"],
            "author_id": tweet["user"]["id_str"],
            "author_avatar_url": "", # todo: add
            "author_banner_url": "", # todo: add
            "verified": "", # todo: add
            "source": strip_tags(tweet["legacy"]["source"]),
            "language_guess": tweet["legacy"].get("lang"),
            "possibly_sensitive": "yes" if tweet["legacy"].get("possibly_sensitive") else "no",
            "retweet_count": tweet["legacy"]["retweet_count"],
            "reply_count": tweet["legacy"]["reply_count"],
            "like_count": tweet["legacy"]["favorite_count"],
            "quote_count": tweet["legacy"]["quote_count"],
            "impression_count": tweet.get("ext_views", {}).get("count", ""),
            "is_retweet": "yes" if retweet else "no",
            "retweeted_user": retweet["result"]["core"]["user_results"]["result"].get("legacy", {}).get("screen_name", "") if retweet else "",
            "is_quote_tweet": "yes" if quote_tweet else "no",
            "quote_tweet_id": "", # todo: add
            "quote_author": quote_tweet["result"]["core"]["user_results"]["result"].get("legacy", {}).get("screen_name", "") if quote_tweet else "",
            "quote_body": "", # todo: add
            "quote_images": "", # todo: add
            "quote_videos": "",  # todo: add
            "is_quote_withheld": "", # todo: add
            "is_reply": "yes" if str(tweet["legacy"]["conversation_id_str"]) != tweet_id else "no",
            "replied_author": tweet["legacy"].get("in_reply_to_screen_name", "") if tweet["legacy"].get(
                "in_reply_to_screen_name") else "",
            "is_withheld": "yes" if withheld else "no",
            "hashtags": ",".join([hashtag["text"] for hashtag in tweet["legacy"]["entities"]["hashtags"]]),
            "urls": ",".join([url.get("expanded_url", url["display_url"]) for url in tweet["legacy"]["entities"]["urls"]]),
            "images": ",".join(
                [media["media_url_https"] for media in tweet["legacy"].get("extended_entities", {}).get("media", []) if
                 media["type"] == "photo"]),
            "videos": ",".join([media["video_info"]["variants"][0]["url"] for media in
                                tweet["legacy"].get("extended_entities", {}).get("media", []) if
                                media["type"] == "video"]),
            "mentions": ",".join([media["screen_name"] for media in tweet["legacy"]["entities"]["user_mentions"]]),
            "long_lat": SearchTwitterViaZeeschuimer.get_centroid(
                tweet["legacy"]["place"]["bounding_box"]["coordinates"]) if tweet["legacy"].get("place") else "",
            "place_name": tweet["legacy"].get("place", {}).get("full_name", "") if tweet["legacy"].get("place") else "",
        }

    @staticmethod
    def get_centroid(box):
        """
        Get centre of a rectangular box

        Convenience function for converting X/Twitter's bounding box coordinates
        to a singular coordinate - simply the centre of the box - because that
        is what is expected for mapped output.

        :param list box:  The box as part of X/Twitter's response
        :return str:  Coordinate, as longitude,latitude.
        """
        box = box[0]
        return ",".join((
            str(round((box[0][0] + box[1][0]) / 2, 6)),
            str(round((box[0][1] + box[1][1]) / 2, 6)),
        ))
