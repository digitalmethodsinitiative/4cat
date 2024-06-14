"""
Import scraped Douyin data
"""
import urllib
import json
import re
from datetime import datetime

from backend.lib.search import Search
from common.lib.item_mapping import MappedItem, MissingMappedField

class SearchDouyin(Search):
    """
    Import scraped Douyin data
    """
    type = "douyin-search"  # job ID
    category = "Search"  # category
    title = "Import scraped Douyin data"  # title displayed in UI
    description = "Import Douyin data collected with an external tool such as Zeeschuimer."  # description displayed in UI
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

            stream_data = item.get("cellRoom", {}).get("rawdata") if item.get("cellRoom") != "$undefined" else {}
            if stream_data:
                # These appear to be streams
                subject = "Stream"
                post_timestamp = datetime.fromtimestamp(stream_data.get("createtime", item.get(
                    "requestTime") / 1000))  # These may only have the timestamp of the request
                video_url = stream_data.get("stream_url").get("flv_pull_url", {}).get("FULL_HD1")
                video_description = stream_data.get("title")
                duration = "Unknown"
                prevent_download = None
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
                if not videos_list:
                    # Image galleries do not have video data
                    video_url = ""
                else:
                    videos = sorted([vid for vid in item.get("video").get("bitRateList")], key=lambda d: d.get("bitRate"),
                                reverse=True)
                    video_url = "https" + videos[0]["playApi"]
                video_description = item["desc"]
                duration = item.get("duration", item.get("video", {}).get("duration", "Unknown"))
                prevent_download = "yes" if item["download"]["prevent"] else "no"
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
            live_watch_count = stats.get("liveWatchCount", MissingMappedField("Unknown"))

            # This is a guess, I have not encountered it
            video_tags = ",".join([tag["tagName"] for tag in item.get("videoTag", []) if "tagName" in tag])

            mix_current_episode = item.get(mix_info_key, {}).get("currentEpisode", "N/A")

        else:
            stream_data = item.get("rawdata", item.get("cell_room", {}).get("rawdata"))
            if stream_data:
                subject = "Stream"
                stream_data = json.loads(stream_data)
                post_timestamp = datetime.fromtimestamp(
                    stream_data.get("create_time", item.get("create_time", metadata.get(
                        "timestamp_collected") / 1000)))  # Some posts appear to have no timestamp! We substitute collection time
                video_url = stream_data.get("stream_url").get("flv_pull_url", {}).get("FULL_HD1")
                video_description = stream_data.get("title")
                duration = "Unknown"

                # Author is stream owner
                author = stream_data.get("owner")
                video_tags = stream_data.get("video_feed_tag")
                stats = stream_data.get("stats")

            else:
                post_timestamp = datetime.fromtimestamp(item["create_time"])
                videos_list = item.get("video").get("bit_rate")
                if not videos_list:
                    # Image galleries do not have video data
                    video_url = ""
                else:
                    videos = sorted([vid for vid in item["video"]["bit_rate"]], key=lambda d: d.get("bit_rate"),
                                reverse=True)
                    video_url = videos[0]["play_addr"].get("url_list", [''])[-1] if len(videos) > 0 else ""
                video_description = item["desc"]
                duration = item.get("duration", item.get("video", {}).get("duration", "Unknown"))

                # Author is, well, author
                author = item["author"]
                stats = item.get("statistics")

            prevent_download = ("yes" if item["prevent_download"] else "no") if "prevent_download" in item else None

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
            live_watch_count = stats.get("live_watch_count") if stats else MissingMappedField("Unknown")

            video_tags = ",".join(
                [tag["tag_name"] for tag in (item["video_tag"] if item["video_tag"] is not None else []) if
                 "tag_name" in tag])

            mix_current_episode = item.get(mix_info_key, {}).get("statis", {}).get("current_episode", "N/A")

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
        music_author = item.get('music').get('author') if item.get('music') and item.get("music") != "$undefined" else ""
        music_title = item.get('music').get('title') if item.get('music') and item.get("music") != "$undefined" else ""
        music_url = item.get('music').get('play_url', {}).get('uri') if item.get('music') and item.get("music") != "$undefined" else ""

        # Collection
        mix_current_episode = mix_current_episode if mix_current_episode != "$undefined" else "N/A"
        collection_id = item.get(mix_info_key, {}).get(mix_id_key, "N/A")
        collection_id = collection_id if collection_id != "$undefined" else "N/A"
        collection_name = item.get(mix_info_key, {}).get(mix_name_key, "N/A")
        collection_name = collection_name if collection_name != "$undefined" else "N/A"
        part_of_collection = "yes" if mix_info_key in item and mix_id_key in item[
            mix_info_key] and collection_id != "N/A" else "no"

        return MappedItem({
            "id": item[aweme_id_key],
            "thread_id": item[group_id_key],
            "subject": subject,
            "body": video_description,
            "timestamp": post_timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "post_source_domain": urllib.parse.unquote(metadata.get("source_platform_url")),
            # Adding this as different Douyin pages contain different data
            "post_url": f"https://www.douyin.com/video/{item[aweme_id_key]}",
            "region": item.get("region", ""),
            "hashtags": ",".join(
                [tag[hashtag_key] for tag in (item[text_extra_key] if item[text_extra_key] is not None else []) if
                 hashtag_key in tag]),
            "mentions": ",".join([f"https://www.douyin.com/user/{tag[mention_key]}" for tag in
                                  (item[text_extra_key] if item[text_extra_key] is not None else []) if
                                  mention_key in tag]),
            # Actual username does not appear in object, but the sec_uid can be used to form a link to their profile
            "video_tags": video_tags,
            "prevent_download": prevent_download,
            "video_url": video_url,
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
