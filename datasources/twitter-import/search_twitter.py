"""
Import scraped X/Twitter data

It's prohibitively difficult to scrape data from Twitter within 4CAT itself due
to its aggressive rate limiting. Instead, import data collected elsewhere.
"""
import re
from datetime import datetime

from backend.lib.search import Search
from common.lib.helpers import strip_tags
from common.lib.item_mapping import MappedItem
from common.lib.helpers import normalize_url_encoding
from common.lib.outputs import Datasource


class SearchTwitterViaZeeschuimer(Search):
    """
    Import scraped X/Twitter data
    """
    type = "twitter-import"  # job ID
    category = "Search"  # category
    title = "Import scraped X/Twitter data"  # title displayed in UI
    description = "Import X/Twitter data collected with an external tool such as Zeeschuimer."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    # the tag column the co-tag and hashtag networks look for
    output = Datasource(columns={"hashtags"})
    is_from_zeeschuimer = True
    icon = "brand-x-twitter"

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

        # The inline user object can also be absent entirely (empty user_results)
        # when Twitter de-duplicates user data elsewhere. Recover what we can: screen_name
        # from any media expanded_url (it embeds the author), author_id from
        # legacy.user_id_str; the rest stays blank.
        has_user_inline = bool(tweet.get("core", {}).get("user_results", {}).get("result"))
        if has_user_inline:
            user_result = tweet["core"]["user_results"]["result"]
            author_screen_name = user_result[user_key]["screen_name"]
            author_fullname = user_result[user_key]["name"]
            author_avatar_url = user_result["avatar"]["image_url"] if "avatar" in user_result else user_result["legacy"].get("profile_image_url_https", "")
            author_banner_url = user_result["legacy"].get("profile_banner_url", "")
            author_verified = user_result.get("is_blue_verified", "")
        else:
            author_screen_name = SearchTwitterViaZeeschuimer._screen_name_from_media(tweet.get("legacy", {}))
            author_fullname = ""
            author_avatar_url = ""
            author_banner_url = ""
            author_verified = ""

        tweet_link = (f"https://x.com/{author_screen_name}/status/{tweet['id']}"
                      if author_screen_name else f"https://x.com/i/web/status/{tweet['rest_id']}")

        timestamp = datetime.strptime(tweet["legacy"]["created_at"], "%a %b %d %H:%M:%S %z %Y")
        withheld = False

        retweet = tweet["legacy"].get("retweeted_status_result")
        retweeted_user = ""
        if retweet:
            # make sure the full RT is included, by default this is shortened
            if "tweet" in retweet["result"]:
                retweet["result"] = retweet["result"]["tweet"]

            # The retweeted tweet is shaped like a regular tweet and can hit
            # the same inline-user-missing quirks. Recover symmetrically with
            # the outer tweet: prefer the inline user object, then fall back
            # to a screen name embedded in any media expanded_url.
            rt_result = retweet["result"]
            rt_user_result = rt_result.get("core", {}).get("user_results", {}).get("result") or {}
            if rt_user_result:
                retweeted_user = rt_user_result.get(user_key, {}).get("screen_name", "") or \
                                 rt_user_result.get("legacy", {}).get("screen_name", "")
            if not retweeted_user:
                retweeted_user = SearchTwitterViaZeeschuimer._screen_name_from_media(rt_result.get("legacy", {}))

            if rt_result.get("legacy", {}).get("withheld_scope"):
                withheld = True
                tweet["legacy"]["full_text"] = rt_result["legacy"]["full_text"]
            else:
                t_text = "RT @" + retweeted_user + ": " + rt_result["legacy"]["full_text"]
                tweet["legacy"]["full_text"] = t_text

        quote_tweet = tweet.get("quoted_status_result")
        if quote_tweet and "tweet" in quote_tweet.get("result", {}):
            # sometimes this is one level deeper, sometimes not...
            quote_tweet["result"] = quote_tweet["result"]["tweet"]
        # check if the quote tweet is available or not
        quote_withheld = True if (quote_tweet and "tombstone" in quote_tweet["result"]) else False

        # Quote tweet may also have its inline user info absent; recover the
        # screen name from any quoted-media expanded_url when that happens.
        if quote_tweet and not quote_withheld:
            quote_result = quote_tweet["result"]
            if quote_result.get("core"):
                quote_author = quote_result["core"]["user_results"]["result"].get(user_key, {}).get("screen_name", "")
            else:
                quote_author = SearchTwitterViaZeeschuimer._screen_name_from_media(quote_result.get("legacy", {}))
        else:
            quote_author = ""

        # extract media from tweet; if video, add thumbnail to images and video link to videos
        images = set()
        videos = set()
        
        # Process media from extended_entities for videos and photos
        for media in tweet["legacy"].get("extended_entities", {}).get("media", []):
            if media["type"] == "photo":
                images.add(media["media_url_https"])
            elif media["type"] == "video":
                # Add video thumbnail to images
                images.add(media["media_url_https"])
                # Add actual video URL to videos if available
                if media.get("video_info", {}).get("variants"):
                    # Filter variants to get video files (not streaming playlists)
                    video_variants = [
                        variant for variant in media["video_info"]["variants"]
                        if variant.get("content_type", "").startswith("video/")
                    ]
                    if video_variants:
                        # Sort by bitrate (highest first) to get best quality
                        video_variants.sort(key=lambda x: x.get("bitrate", 0), reverse=True)
                        videos.add(video_variants[0]["url"])
        
        # Also check entities.media for any additional photos not in extended_entities
        for media in tweet["legacy"]["entities"].get("media", []):
            if media["type"] == "photo":
                images.add(media["media_url_https"])

        return {
            "collected_from_url": normalize_url_encoding(tweet.get("__import_meta", {}).get("source_platform_url", "")),  # Zeeschuimer metadata
            "id": tweet["rest_id"],
            "thread_id": tweet["legacy"]["conversation_id_str"],
            "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "unix_timestamp": int(timestamp.timestamp()),
            "link": tweet_link,
            "body": tweet["legacy"]["full_text"],
            "author": author_screen_name,
            "author_fullname": author_fullname,
            "author_id": tweet["legacy"]["user_id_str"],
            "author_avatar_url": author_avatar_url,
            "author_banner_url": author_banner_url,
            "verified": author_verified,
            "source": strip_tags(tweet["source"]),
            "language_guess": tweet["legacy"].get("lang"),
            "possibly_sensitive": "yes" if tweet.get("possibly_sensitive", False) or tweet["legacy"].get("possibly_sensitive", False) else "no",
            "retweet_count": tweet["legacy"]["retweet_count"],
            "reply_count": tweet["legacy"]["reply_count"],
            "like_count": tweet["legacy"]["favorite_count"],
            "quote_count": tweet["legacy"]["quote_count"],
            "impression_count": tweet.get("views", {}).get("count", ""),
            "is_retweet": "yes" if retweet else "no",
            "retweeted_user": retweeted_user,
            "is_quote_tweet": "yes" if quote_tweet else "no",
            "quote_tweet_id": quote_tweet["result"].get("rest_id", "") if quote_tweet else "",
            "quote_author": quote_author,
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
            "hashtags": ",".join([hashtag["text"] for hashtag in tweet["legacy"]["entities"].get("hashtags", [])]),
            "urls": ",".join([url.get("expanded_url", url["display_url"]) for url in tweet["legacy"]["entities"].get("urls", [])]),
            "images": ",".join(images),
            "videos": ",".join(videos),
            "mentions": ",".join([mention["screen_name"] for mention in tweet["legacy"]["entities"].get("user_mentions", [])]),
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
            "collected_from_url": normalize_url_encoding(tweet.get("__import_meta", {}).get("source_platform_url", "")),  # Zeeschuimer metadata
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
            "hashtags": ",".join([hashtag["text"] for hashtag in tweet["legacy"]["entities"].get("hashtags", [])]),
            "urls": ",".join([url.get("expanded_url", url["display_url"]) for url in tweet["legacy"]["entities"].get("urls", [])]),
            "images": ",".join(
                [media["media_url_https"] for media in tweet["legacy"].get("extended_entities", {}).get("media", []) if
                 media["type"] == "photo"]),
            "videos": ",".join([media["video_info"]["variants"][0]["url"] for media in
                                tweet["legacy"].get("extended_entities", {}).get("media", []) if
                                media["type"] == "video"]),
            "mentions": ",".join([mention["screen_name"] for mention in tweet["legacy"]["entities"].get("user_mentions", [])]),
            "long_lat": SearchTwitterViaZeeschuimer.get_centroid(
                tweet["legacy"]["place"]["bounding_box"]["coordinates"]) if tweet["legacy"].get("place") else "",
            "place_name": tweet["legacy"].get("place", {}).get("full_name", "") if tweet["legacy"].get("place") else "",
        }

    @staticmethod
    def _screen_name_from_media(legacy_obj):
        """
        Recover a tweet author's screen name from any embedded media URL.

        Twitter's media `expanded_url` always has the form
        `https://x.com/<screen_name>/status/<id>/...`, so when inline user
        info is missing this is a reliable fallback.
        """
        if not isinstance(legacy_obj, dict):
            return ""
        for container in ("extended_entities", "entities"):
            for m in legacy_obj.get(container, {}).get("media", []) or []:
                url = m.get("expanded_url", "") if isinstance(m, dict) else ""
                match = re.match(r"^https?://(?:x|twitter)\.com/([^/]+)/status/", url)
                if match:
                    return match.group(1)
        return ""

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
        try:
            ring = box[0]
            if len(ring) < 2 or not ring[0] or not ring[1]:
                return ""
            return ",".join((
                str(round((ring[0][0] + ring[1][0]) / 2, 6)),
                str(round((ring[0][1] + ring[1][1]) / 2, 6)),
            ))
        except (IndexError, TypeError):
            return ""
