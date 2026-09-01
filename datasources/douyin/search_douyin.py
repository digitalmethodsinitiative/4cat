"""
Import scraped Douyin data
"""
import json
import re
from datetime import datetime

from backend.lib.search import Search
from common.lib.item_mapping import MappedItem, MissingMappedField
from common.lib.helpers import normalize_url_encoding


def defined(data, key, default=None):
    """
    Read a value from Douyin page data.

    Douyin pages embed data in which a value that was never set arrives as the
    string "$undefined" instead of being left out. Treat that placeholder the
    same as a missing key. A key that is present and null is left alone, since
    a null may be the source saying "none" rather than "not set".

    :param dict data:  Object to read from
    :param str key:  Key to read
    :param default:  Value to return if the key is absent or was never set
    :return:  The stored value, or the default
    """
    value = data.get(key, default)
    return default if value == "$undefined" else value


def absolute_link(url):
    """
    Make a link openable.

    Douyin sometimes leaves the "https:" off the front of a link, so that it
    starts straight at "//". Put it back; leave other links as they are.

    :param str url:  Link from the post data
    :return str:  Link that can be opened
    """
    return "https:" + url if url.startswith("//") else url


def first_link(*sources):
    """
    Get the first usable link from a number of places in the post data.

    Douyin keeps links in a "url_list", but sometimes fills that list with
    scrambled text instead, so an entry is only usable if it starts like a web
    address. Sources are tried in order, so pass the preferred one first.

    :param sources:  Objects that may hold a "url_list"
    :return str:  The first usable link, or an empty string if there is none
    """
    for source in sources:
        for url in (source or {}).get("url_list") or []:
            if isinstance(url, str) and url.startswith(("http://", "https://", "//")):
                return absolute_link(url)
    return ""


def stream_link(stream_data):
    """
    Get the best available video link for a live stream.

    Douyin offers a stream at several qualities, but not always the same ones,
    so work down from the best. An unfamiliar quality name is still better than
    no link at all, so anything left over is used as a last resort.

    :param dict stream_data:  The stream's own data, from "rawdata"
    :return str:  Link to the stream, or an empty string if none is offered
    """
    qualities = (stream_data.get("stream_url") or {}).get("flv_pull_url") or {}
    for quality in ("FULL_HD1", "HD1", "SD1", "SD2"):
        if qualities.get(quality):
            return absolute_link(qualities[quality])

    for link in qualities.values():
        if link:
            return absolute_link(link)

    return ""


def download_prevented(download):
    """
    Work out whether Douyin blocks downloading a video.

    Two opposite flags have been used for this: "prevent", where true means
    downloading is blocked, and the newer "allowDownload", where true means it
    is allowed. Report a missing field when neither is there, rather than
    guessing which way round it was.

    :param dict download:  The post's "download" object
    :return:  "yes", "no", or a MissingMappedField
    """
    if isinstance(download, dict):
        if "prevent" in download:
            return "yes" if download["prevent"] else "no"
        if "allowDownload" in download:
            return "no" if download["allowDownload"] else "yes"

    return MissingMappedField("Unknown")


class SearchDouyin(Search):
    """
    Import scraped Douyin data
    """
    type = "douyin-search"  # job ID
    category = "Search"  # category
    title = "Import scraped Douyin data"  # title displayed in UI
    description = "Import Douyin data collected with an external tool such as Zeeschuimer."  # description displayed in UI
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

        Not available for Douyin
        """
        raise NotImplementedError("Douyin datasets can only be created by importing data from elsewhere")

    @staticmethod
    def map_item(item):
        """
        """
        metadata = item.get("__import_meta")
        subject = "Post"
        if "ZS_collected_from_embed" in item and item["ZS_collected_from_embed"]:
            # HTML embedded posts formated differently than JSON posts

            stream_data = defined(item, "cellRoom", {}).get("rawdata")
            if stream_data:
                # These appear to be streams
                subject = "Stream"
                post_timestamp = datetime.fromtimestamp(stream_data.get("createtime", item.get(
                    "requestTime") / 1000))  # These may only have the timestamp of the request
                video_url = stream_link(stream_data)
                video_thumbnail = stream_data.get("video", {}).get("cover")
                video_description = stream_data.get("title")
                duration = "Unknown"
                prevent_download = MissingMappedField("Unknown")
                stats = stream_data.get("stats")

                # Author is stream owner
                author = stream_data.get("owner")
                author_sec_key = "sec_uid"
                avatar_thumb_key = "avatar_thumb"
                url_list_key = "url_list"
                is_fake_key = "is_ad_fake"  # have not seen...
            else:
                post_timestamp = datetime.fromtimestamp(item["createTime"])
                videos_list = item.get("video").get("bitRateList")
                if videos_list:
                    videos = sorted([vid for vid in item.get("video").get("bitRateList")], key=lambda d: d.get("bitRate"),
                                reverse=True)
                    video_url = absolute_link(videos[0].get("playApi", ""))
                else:
                    video_url = ""
                video_thumbnail = item.get("video", {}).get("cover")
                video_description = item["desc"]
                duration = item.get("duration", item.get("video", {}).get("duration", "Unknown"))
                prevent_download = download_prevented(defined(item, "download", {}))
                stats = item["stats"]

                # Author is, well, author
                author = item["authorInfo"]
                author_sec_key = "secUid"
                avatar_thumb_key = "avatarThumb"
                url_list_key = "urlList"
                is_fake_key = "isAdFake"

            # Embedded Keys
            aweme_id_key = "awemeId"
            group_id_key = "groupId"
            text_extra_key = "textExtra"
            hashtag_key = "hashtagName"
            mention_key = "secUid"
            author_id_key = "authorUserId"
            mix_info_key = "mixInfo"
            mix_id_key = "mixId"
            mix_name_key = "mixName"

            # Stats
            collect_count = stats.get("collectCount", MissingMappedField("Unknown"))
            comment_count = stats.get("commentCount", MissingMappedField("Unknown"))
            digg_count = stats.get("diggCount", MissingMappedField("Unknown"))
            download_count = stats.get("downloadCount", MissingMappedField("Unknown"))
            forward_count = stats.get("forwardCount", MissingMappedField("Unknown"))
            play_count = stats.get("playCount", MissingMappedField("Unknown"))
            share_count = stats.get("shareCount", MissingMappedField("Unknown"))
            # live_watch_count = stats.get("liveWatchCount", MissingMappedField("Unknown"))

            # Normally a list of tag objects. If the tags arrive as a plain string instead,
            # keep what was sent rather than discarding it.
            video_tag_list = defined(item, "videoTag")
            if isinstance(video_tag_list, list):
                video_tags = ",".join([tag["tagName"] for tag in video_tag_list if tag.get("tagName")])
            elif isinstance(video_tag_list, str):
                video_tags = video_tag_list
            else:
                video_tags = ""

            mix_info = defined(item, mix_info_key, {}) or {}
            mix_current_episode = defined(mix_info, "currentEpisode", "N/A")

        else:
            stream_data = item.get("rawdata", item.get("cell_room", {}).get("rawdata"))
            if stream_data:
                subject = "Stream"
                stream_data = json.loads(stream_data)
                post_timestamp = datetime.fromtimestamp(
                    stream_data.get("create_time", item.get("create_time", metadata.get(
                        "timestamp_collected") / 1000)))  # Some posts appear to have no timestamp! We substitute collection time
                video_url = stream_link(stream_data)
                video_thumbnail = stream_data.get("video", {}).get("cover")
                video_description = stream_data.get("title")
                duration = "Unknown"

                # Author is stream owner
                author = stream_data.get("owner")
                stats = stream_data.get("stats")

            else:
                post_timestamp = datetime.fromtimestamp(item["create_time"])
                videos_list = item.get("video").get("bit_rate")
                if not videos_list:
                    # Image galleries do not have video data
                    video_url = ""
                    video_thumbnail = ""
                else:
                    videos = sorted([vid for vid in item["video"]["bit_rate"]], key=lambda d: d.get("bit_rate"),
                                reverse=True)
                    # play_addr is sometimes scrambled rather than a link; download_addr
                    # carries a working one for those posts
                    video_url = first_link(videos[0].get("play_addr"), item.get("video", {}).get("download_addr"))
                    video_thumbnail = item.get("video", {}).get("cover",{}).get("url_list", [""])[0]
                video_description = item["desc"]
                duration = item.get("duration", item.get("video", {}).get("duration", "Unknown"))

                # Author is, well, author
                author = item["author"]
                stats = item.get("statistics")

            prevent_download = ("yes" if item["prevent_download"] else "no") if "prevent_download" in item else MissingMappedField("Unknown")

            # Keys
            aweme_id_key = "aweme_id"
            group_id_key = "group_id"
            text_extra_key = "text_extra"
            hashtag_key = "hashtag_name"
            mention_key = "sec_uid"
            author_id_key = "author_user_id"
            mix_info_key = "mix_info"
            mix_id_key = "mix_id"
            mix_name_key = "mix_name"

            author_sec_key = "sec_uid"
            avatar_thumb_key = "avatar_thumb"
            url_list_key = "url_list"
            is_fake_key = "is_ad_fake"

            # Stats
            collect_count = stats.get("collect_count") if stats else MissingMappedField("Unknown")
            comment_count = stats.get("comment_count") if stats else MissingMappedField("Unknown")
            digg_count = stats.get("digg_count") if stats else MissingMappedField("Unknown")
            download_count = stats.get("download_count") if stats else MissingMappedField("Unknown")
            forward_count = stats.get("forward_count") if stats else MissingMappedField("Unknown")
            play_count = stats.get("play_count") if stats else MissingMappedField("Unknown")
            share_count = stats.get("share_count") if stats else MissingMappedField("Unknown")
            # live_watch_count = stats.get("live_watch_count") if stats else MissingMappedField("Unknown")

            # Covers streams too: they have no tags of their own. A stream's "video_feed_tag" is the
            # caption of the "live now" badge shown on its thumbnail, not a topic, so it is not used here.
            video_tags = ",".join(
                [tag["tag_name"] for tag in (item["video_tag"] if item["video_tag"] is not None else []) if
                 tag.get("tag_name")])

            mix_info = defined(item, mix_info_key, {}) or {}
            mix_current_episode = defined(mix_info.get("statis", {}), "current_episode", "N/A")

        # Stream Stats
        count_total_streams_viewers = stats.get("total_user", "N/A")
        count_current_stream_viewers = SearchDouyin.get_chinese_number(stats.get("user_count_str")) if "user_count_str" in stats else "N/A"

        # Some videos are collected from "mixes"/"collections"; only the first video is definitely displayed while others may or may not be viewed
        displayed = True
        if item.get("ZS_collected_from_mix") and not item.get("ZS_first_mix_vid"):
            displayed = False

        # Image galleries have been added to Douyin
        image_urls = []
        if item.get("images"):
            for img in item["images"]:
                if "url_list" in img:
                    image_urls.append(img["url_list"][0])
                elif "urlList" in img:
                    image_urls.append(img["urlList"][0])

        # Music
        music = defined(item, "music", {}) or {}
        music_author = music.get("author", "")
        music_title = music.get("title", "")
        music_url = music.get("play_url", {}).get("uri") if music else ""

        # Collection
        collection_id = defined(mix_info, mix_id_key, "N/A")
        collection_name = defined(mix_info, mix_name_key, "N/A")
        part_of_collection = "yes" if mix_id_key in mix_info and collection_id != "N/A" else "no"

        return MappedItem({
            "collected_from_url": normalize_url_encoding(metadata.get("source_platform_url", "")),
            "id": item[aweme_id_key],
            "thread_id": item[group_id_key],
            "subject": subject,
            "body": video_description,
            "timestamp": post_timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            # Adding this as different Douyin pages contain different data
            "post_url": f"https://www.douyin.com/video/{item[aweme_id_key]}" if subject == "Post" else f"https://live.douyin.com/{author.get('web_rid')}",
            "region": item.get("region", ""),
            "hashtags": ",".join(
                [tag[hashtag_key] for tag in (item[text_extra_key] if item[text_extra_key] is not None else []) if
                 tag.get(hashtag_key)]),
            "mentions": ",".join([f"https://www.douyin.com/user/{tag[mention_key]}" for tag in
                                  (item[text_extra_key] if item[text_extra_key] is not None else []) if
                                  tag.get(mention_key)]),
            # Actual username does not appear in object, but the sec_uid can be used to form a link to their profile
            "video_tags": video_tags,
            "prevent_download": prevent_download,
            "video_url": video_url,
            "video_thumbnail": video_thumbnail,
            "video_duration": duration,
            "image_urls": ','.join(image_urls),
            "music_author": music_author,
            "music_title": music_title,
            "music_url": music_url,
            # Video stats
            "collect_count": collect_count,
            "comment_count": comment_count,
            "digg_count": digg_count,
            "download_count": download_count,
            "forward_count": forward_count,
            "play_count": play_count,
            "share_count": share_count,
            "count_total_streams_viewers": count_total_streams_viewers,
            "count_current_stream_viewers": count_current_stream_viewers,
            # Author data
            "author_user_id": item[author_id_key] if author_id_key in item else author.get("uid", author.get("id")),
            "author_nickname": author["nickname"],
            "author_profile_url": f"https://www.douyin.com/user/{author[author_sec_key]}",
            "author_thumbnail_url": author[avatar_thumb_key].get(url_list_key, [''])[0],
            "author_region": author.get("region"),
            "author_is_ad_fake": author.get(is_fake_key),
            # Collection/Mix
            "part_of_collection": part_of_collection,
            "4CAT_first_video_displayed": "yes" if displayed else "no",
            # other videos may have been viewed, but this is unknown to us
            "collection_id": collection_id,
            "collection_name": collection_name,
            "place_in_collection": mix_current_episode,
            "unix_timestamp": int(post_timestamp.timestamp()),
        })

    @staticmethod
    def get_chinese_number(num):
        if type(num) in (float, int):
            return num
        elif type(num) is not str:
            return 0

        if "万" in num:
            return float(re.sub(r"[^0-9.]", "", num)) * 10000
        else:
            return int(re.sub(r"[^0-9.]", "", num))
