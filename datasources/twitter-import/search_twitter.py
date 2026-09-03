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

        # The user object can be absent entirely (empty user_results) when X
        # de-duplicates user data elsewhere. Recover what we can: the screen name
        # from any media expanded_url (it embeds the author), the author ID from
        # legacy.user_id_str; the rest stays blank.
        user_result = tweet.get("core", {}).get("user_results", {}).get("result") or {}
        author = SearchTwitterViaZeeschuimer.map_user(user_result)
        author_screen_name = author["screen_name"] or \
            SearchTwitterViaZeeschuimer._screen_name_from_media(tweet.get("legacy", {}))
        author_fullname = author["fullname"]
        author_avatar_url = author["avatar_url"]
        author_banner_url = author["banner_url"]
        author_verified = author["verified"]
        author_followers = author["followers"]
        author_following = author["following"]
        author_bio = author["bio"]
        author_location = author["location"]

        tweet_link = (f"https://x.com/{author_screen_name}/status/{tweet['id']}"
                      if author_screen_name else f"https://x.com/i/web/status/{tweet['rest_id']}")

        timestamp = datetime.strptime(tweet["legacy"]["created_at"], "%a %b %d %H:%M:%S %z %Y")
        withheld = False

        body = SearchTwitterViaZeeschuimer.get_full_text(tweet)

        retweet = tweet["legacy"].get("retweeted_status_result")
        retweeted_user = ""
        if retweet:
            # make sure the full RT is included, by default this is shortened
            if "tweet" in retweet["result"]:
                retweet["result"] = retweet["result"]["tweet"]

            # The retweeted post is shaped like a regular post and can have the same
            # missing user object. Recover it the same way as for the outer post:
            # prefer the user object, then fall back to a screen name embedded in
            # any media expanded_url.
            rt_result = retweet["result"]
            rt_user_result = rt_result.get("core", {}).get("user_results", {}).get("result") or {}
            retweeted_user = SearchTwitterViaZeeschuimer.map_user(rt_user_result)["screen_name"] or \
                SearchTwitterViaZeeschuimer._screen_name_from_media(rt_result.get("legacy", {}))

            if rt_result.get("legacy", {}).get("withheld_scope"):
                withheld = True
                body = SearchTwitterViaZeeschuimer.get_full_text(rt_result)
            else:
                body = "RT @" + retweeted_user + ": " + SearchTwitterViaZeeschuimer.get_full_text(rt_result)

        quote_tweet = tweet.get("quoted_status_result")
        if quote_tweet and "tweet" in quote_tweet.get("result", {}):
            # sometimes this is one level deeper, sometimes not...
            quote_tweet["result"] = quote_tweet["result"]["tweet"]
        # check if the quote tweet is available or not
        quote_withheld = True if (quote_tweet and "tombstone" in quote_tweet["result"]) else False

        # The quoted post may also have its user object absent; recover the screen
        # name from any quoted media expanded_url when that happens.
        quote_author = ""
        quote_body = ""
        quote_images = set()
        quote_videos = set()
        if quote_tweet and not quote_withheld:
            quote_result = quote_tweet["result"]
            quote_user_result = quote_result.get("core", {}).get("user_results", {}).get("result") or {}
            quote_author = SearchTwitterViaZeeschuimer.map_user(quote_user_result)["screen_name"] or \
                SearchTwitterViaZeeschuimer._screen_name_from_media(quote_result.get("legacy", {}))
            quote_body = SearchTwitterViaZeeschuimer.get_full_text(quote_result)
            quote_images, quote_videos = SearchTwitterViaZeeschuimer.get_media(quote_result)

        # X does not always include the quoted post itself, but a post that quotes
        # another always records the quoted post's ID and a link to it. Read those
        # separately - otherwise these posts look like ordinary posts, and the link
        # between the two is lost.
        quote_tweet_id = tweet["legacy"].get("quoted_status_id_str", "")
        if not quote_tweet_id and quote_tweet:
            quote_tweet_id = quote_tweet["result"].get("rest_id", "")
        is_quote_tweet = bool(quote_tweet_id or quote_tweet or tweet["legacy"].get("is_quote_status"))
        if not quote_author:
            quote_author = SearchTwitterViaZeeschuimer._screen_name_from_url(
                tweet["legacy"].get("quoted_status_permalink", {}).get("expanded", ""))

        images, videos = SearchTwitterViaZeeschuimer.get_media(tweet)
        entities = SearchTwitterViaZeeschuimer.get_entities(tweet)

        return {
            "collected_from_url": normalize_url_encoding(tweet.get("__import_meta", {}).get("source_platform_url", "")),  # Zeeschuimer metadata
            "id": tweet["rest_id"],
            "thread_id": tweet["legacy"]["conversation_id_str"],
            "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "unix_timestamp": int(timestamp.timestamp()),
            "link": tweet_link,
            "body": body,
            "author": author_screen_name,
            "author_fullname": author_fullname,
            "author_id": tweet["legacy"]["user_id_str"],
            "author_avatar_url": author_avatar_url,
            "author_banner_url": author_banner_url,
            "author_followers": author_followers,
            "author_following": author_following,
            "author_bio": author_bio,
            "author_location": author_location,
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
            "is_quote_tweet": "yes" if is_quote_tweet else "no",
            "quote_tweet_id": quote_tweet_id,
            "quote_author": quote_author,
            "quote_body": quote_body,
            "quote_images": ",".join(quote_images),
            "quote_videos": ",".join(quote_videos),
            "is_quote_withheld": "yes" if quote_withheld else "no",
            "is_reply": "yes" if str(tweet["legacy"]["conversation_id_str"]) != str(tweet["rest_id"]) else "no",
            "replied_author": tweet["legacy"].get("in_reply_to_screen_name", ""),
            "is_withheld": "yes" if withheld else "no",
            "hashtags": ",".join([hashtag["text"] for hashtag in entities.get("hashtags", [])]),
            "urls": ",".join([url.get("expanded_url", url["display_url"]) for url in entities.get("urls", [])]),
            "images": ",".join(images),
            "videos": ",".join(videos),
            "mentions": ",".join([mention["screen_name"] for mention in entities.get("user_mentions", [])]),
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

        # a post that quotes another always records the quoted post's ID and a link
        # to it, even when the quoted post itself is not included
        quote_tweet_id = tweet["legacy"].get("quoted_status_id_str", "")
        if not quote_tweet_id and quote_tweet:
            quote_tweet_id = quote_tweet["result"].get("rest_id", "")
        is_quote_tweet = bool(quote_tweet_id or quote_tweet or tweet["legacy"].get("is_quote_status"))
        quote_author = quote_tweet["result"]["core"]["user_results"]["result"].get("legacy", {}).get(
            "screen_name", "") if quote_tweet else ""
        if not quote_author:
            quote_author = SearchTwitterViaZeeschuimer._screen_name_from_url(
                tweet["legacy"].get("quoted_status_permalink", {}).get("expanded", ""))

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
            "author_followers": tweet["user"].get("followers_count", ""),
            "author_following": tweet["user"].get("friends_count", ""),
            "author_bio": tweet["user"].get("description", ""),
            "author_location": tweet["user"].get("location", ""),
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
            "is_quote_tweet": "yes" if is_quote_tweet else "no",
            "quote_tweet_id": quote_tweet_id,
            "quote_author": quote_author,
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
    def map_user(user_result):
        """
        Read an author's details from a post's user object.

        X has changed the shape of this object twice. The oldest posts keep every
        detail in a `legacy` object. A later version added `core` and `avatar`
        objects next to it. The newest version drops `legacy` entirely and spreads
        its contents over `core`, `avatar` and `banner`. Read whichever of these
        is present, so posts collected at any point still map.

        The move happened detail by detail, so a single post can have some details
        in the new place and others still in `legacy`.

        :param dict user_result:  The user object, i.e. the `result` under a post's
                                  `core.user_results`. May be empty.
        :return dict:  Author details, with empty strings for anything unavailable.
        """
        if not isinstance(user_result, dict):
            user_result = {}

        core = user_result.get("core") or {}
        legacy = user_result.get("legacy") or {}
        avatar = user_result.get("avatar") or {}
        banner = user_result.get("banner") or {}
        counts = user_result.get("relationship_counts") or {}
        profile_bio = user_result.get("profile_bio") or {}
        location = user_result.get("location") or {}

        def first(*values):
            # the first detail that X actually provided; keeps values that are
            # legitimately empty or zero, such as an empty bio or no followers
            for value in values:
                if value is not None:
                    return value
            return ""

        return {
            "screen_name": core.get("screen_name") or legacy.get("screen_name", ""),
            "fullname": core.get("name") or legacy.get("name", ""),
            "avatar_url": avatar.get("image_url") or legacy.get("profile_image_url_https", ""),
            "banner_url": banner.get("image_url") or legacy.get("profile_banner_url", ""),
            "verified": user_result.get("is_blue_verified", ""),
            "followers": first(counts.get("followers"), legacy.get("followers_count")),
            "following": first(counts.get("following"), legacy.get("friends_count")),
            "bio": first(profile_bio.get("description"), legacy.get("description")),
            "location": first(location.get("location"), legacy.get("location")),
        }

    @staticmethod
    def get_note_result(tweet):
        """
        Get the extra data X stores for posts longer than 280 characters.

        Such posts are stored twice: `legacy` holds a shortened version, and
        `note_tweet` holds the whole post. The shortened version is returned by
        default, so the `note_tweet` data needs to be read separately.

        :param dict tweet:  A post object.
        :return dict:  The note data, or an empty dictionary for shorter posts.
        """
        note = tweet.get("note_tweet") or {}
        return note.get("note_tweet_results", {}).get("result") or {}

    @staticmethod
    def get_full_text(tweet):
        """
        Get a post's complete text.

        For posts longer than 280 characters the text in `legacy` is cut off, and
        the whole post is stored in `note_tweet` instead. Use whichever is longer.

        :param dict tweet:  A post object.
        :return str:  The post's text.
        """
        text = tweet.get("legacy", {}).get("full_text", "")
        note_text = SearchTwitterViaZeeschuimer.get_note_result(tweet).get("text", "")
        return note_text if len(note_text) > len(text) else text

    @staticmethod
    def get_entities(tweet):
        """
        Get the hashtags, links and mentions in a post.

        For posts longer than 280 characters the entities in `legacy` only cover
        the part of the post that was not cut off - usually leaving them empty -
        so read them from `note_tweet` instead when it holds the longer text.
        Attached media is only ever listed in `legacy`.

        :param dict tweet:  A post object.
        :return dict:  Entities, in the shape X uses in `legacy.entities`.
        """
        entities = tweet.get("legacy", {}).get("entities") or {}
        note = SearchTwitterViaZeeschuimer.get_note_result(tweet)
        note_entities = note.get("entity_set")
        if not note_entities:
            return entities

        if len(note.get("text", "")) <= len(tweet.get("legacy", {}).get("full_text", "")):
            return entities

        combined = dict(note_entities)
        if entities.get("media"):
            combined["media"] = entities["media"]
        return combined

    @staticmethod
    def get_media(tweet):
        """
        Get the images and videos attached to a post.

        Videos and animated GIFs are stored as a still image plus a list of files
        in various qualities; take the still image as the image and the highest
        quality video file as the video. Streaming playlists are skipped because
        they cannot be downloaded as a single file.

        :param dict tweet:  A post object.
        :return tuple:  A set of image URLs and a set of video URLs.
        """
        images = set()
        videos = set()

        legacy = tweet.get("legacy") or {}
        # extended_entities lists every attachment; entities may list only the
        # first one, but is the only place media appears in some older posts
        media_items = list(legacy.get("extended_entities", {}).get("media") or [])
        media_items += list(legacy.get("entities", {}).get("media") or [])

        for media in media_items:
            if not media.get("media_url_https"):
                continue

            # the still image, both for photos and as a video thumbnail
            images.add(media["media_url_https"])

            if media.get("type") not in ("video", "animated_gif"):
                continue

            video_variants = [
                variant for variant in (media.get("video_info") or {}).get("variants") or []
                if variant.get("content_type", "").startswith("video/")
            ]
            if video_variants:
                video_variants.sort(key=lambda variant: variant.get("bitrate", 0), reverse=True)
                videos.add(video_variants[0]["url"])

        return images, videos

    @staticmethod
    def _screen_name_from_url(url):
        """
        Read an author's screen name from a link to one of their posts.

        Links to a post always have the form
        `https://x.com/<screen_name>/status/<id>`, so they can stand in for a
        missing user object.

        :param str url:  A link to a post.
        :return str:  The screen name, or an empty string for any other link.
        """
        if not isinstance(url, str):
            return ""
        match = re.match(r"^https?://(?:x|twitter)\.com/([^/]+)/status/", url)
        return match.group(1) if match else ""

    @staticmethod
    def _screen_name_from_media(legacy_obj):
        """
        Recover a post author's screen name from any attached media link.

        A media item's `expanded_url` links to the post it is attached to, so
        when the user object is missing this is a reliable fallback.
        """
        if not isinstance(legacy_obj, dict):
            return ""
        for container in ("extended_entities", "entities"):
            for m in legacy_obj.get(container, {}).get("media", []) or []:
                url = m.get("expanded_url", "") if isinstance(m, dict) else ""
                screen_name = SearchTwitterViaZeeschuimer._screen_name_from_url(url)
                if screen_name:
                    return screen_name
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
