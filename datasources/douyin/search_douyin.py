"""
Import scraped Douyin data
"""
import urllib
import json
import re
from datetime import datetime

from backend.lib.search import Search


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
    def map_item(post):
        """
        """
        metadata = post.get("__import_meta")
        subject = "Post"
        if "ZS_collected_from_embed" in post and post["ZS_collected_from_embed"]:
            # HTML embedded posts formated differently than JSON posts

            stream_data = post.get("cellRoom", {}).get("rawdata")
            if stream_data:
                # These appear to be streams
                subject = "Stream"
                post_timestamp = datetime.fromtimestamp(stream_data.get("createtime", post.get(
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
                post_timestamp = datetime.fromtimestamp(post["createTime"])
                videos = sorted([vid for vid in post.get("video").get("bitRateList")], key=lambda d: d.get("bitRate"),
                                reverse=True)
                video_url = "https" + videos[0]["playApi"]
                video_description = post["desc"]
                duration = post.get("duration", post.get("video", {}).get("duration", "Unknown"))
                prevent_download = "yes" if post["download"]["prevent"] else "no"
                stats = post["stats"]

                # Author is, well, author
                author = post["authorInfo"]
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
            collect_count = stats["collectCount"]
            comment_count = stats["commentCount"]
            digg_count = stats["diggCount"]
            download_count = stats["downloadCount"]
            forward_count = stats["forwardCount"]
            play_count = stats["playCount"]
            share_count = stats["shareCount"]
            live_watch_count = stats["liveWatchCount"]

            # This is a guess, I have not encountered it
            video_tags = ",".join([item["tagName"] for item in post.get("videoTag", []) if "tagName" in item])

            mix_current_episode = post.get(mix_info_key, {}).get("currentEpisode", "N/A")

        else:
            stream_data = post.get("rawdata", post.get("cell_room", {}).get("rawdata"))
            if stream_data:
                subject = "Stream"
                stream_data = json.loads(stream_data)
                post_timestamp = datetime.fromtimestamp(
                    stream_data.get("create_time", post.get("create_time", metadata.get(
                        "timestamp_collected") / 1000)))  # Some posts appear to have no timestamp! We substitute collection time
                video_url = stream_data.get("stream_url").get("flv_pull_url", {}).get("FULL_HD1")
                video_description = stream_data.get("title")
                duration = "Unknown"

                # Author is stream owner
                author = stream_data.get("owner")
                video_tags = stream_data.get("video_feed_tag")
                stats = stream_data.get("stats")

            else:
                post_timestamp = datetime.fromtimestamp(post["create_time"])
                videos = sorted([vid for vid in post["video"]["bit_rate"]], key=lambda d: d.get("bit_rate"),
                                reverse=True)
                video_description = post["desc"]
                video_url = videos[0]["play_addr"].get("url_list", [''])[-1] if len(videos) > 0 else ""
                duration = post.get("duration", post.get("video", {}).get("duration", "Unknown"))

                # Author is, well, author
                author = post["author"]
                video_tags = ",".join(
                    [item["tag_name"] for item in (post["video_tag"] if post["video_tag"] is not None else []) if
                     "tag_name" in item])
                stats = post.get("statistics")

            prevent_download = ("yes" if post["prevent_download"] else "no") if "prevent_download" in post else None

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
            collect_count = stats.get("collect_count") if stats else "Unknown"
            comment_count = stats.get("comment_count") if stats else "Unknown"
            digg_count = stats.get("digg_count") if stats else "Unknown"
            download_count = stats.get("download_count") if stats else "Unknown"
            forward_count = stats.get("forward_count") if stats else "Unknown"
            play_count = stats.get("play_count") if stats else "Unknown"
            share_count = stats.get("share_count") if stats else "Unknown"
            live_watch_count = stats.get("live_watch_count") if stats else "Unknown"

            video_tags = ",".join(
                [item["tag_name"] for item in (post["video_tag"] if post["video_tag"] is not None else []) if
                 "tag_name" in item])

            mix_current_episode = post.get(mix_info_key, {}).get("statis", {}).get("current_episode", "N/A")

        # Stream Stats
        count_total_streams_viewers = stats.get("total_user", "N/A")
        stream_viewers = stats.get("user_count_str", "")
        count_current_stream_viewers = SearchDouyin.get_chinese_number(stats.get("user_count_str")) if "user_count_str" in stats else "N/A"

        # Some videos are collected from "mixes"/"collections"; only the first video is definitely displayed while others may or may not be viewed
        displayed = True
        if post.get("ZS_collected_from_mix") and not post.get("ZS_first_mix_vid"):
            displayed = False

        return {
            "id": post[aweme_id_key],
            "thread_id": post[group_id_key],
            "subject": subject,
            "body": video_description,
            "timestamp": post_timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "post_source_domain": urllib.parse.unquote(metadata.get("source_platform_url")),
            # Adding this as different Douyin pages contain different data
            "post_url": f"https://www.douyin.com/video/{post[aweme_id_key]}",
            "region": post.get("region"),
            "hashtags": ",".join(
                [item[hashtag_key] for item in (post[text_extra_key] if post[text_extra_key] is not None else []) if
                 hashtag_key in item]),
            "mentions": ",".join([f"https://www.douyin.com/user/{item[mention_key]}" for item in
                                  (post[text_extra_key] if post[text_extra_key] is not None else []) if
                                  mention_key in item]),
            # Actual username does not appear in object, but the sec_uid can be used to form a link to their profile
            "video_tags": video_tags,
            "prevent_download": prevent_download,
            "video_url": video_url,
            "video_duration": duration,
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
            "author_user_id": post[author_id_key] if author_id_key in post else author.get("uid", author.get("id")),
            "author_nickname": author["nickname"],
            "author_profile_url": f"https://www.douyin.com/user/{author[author_sec_key]}",
            "author_thumbnail_url": author[avatar_thumb_key].get(url_list_key, [''])[0],
            "author_region": author.get("region"),
            "author_is_ad_fake": author.get(is_fake_key),
            # Collection/Mix
            "part_of_collection": "yes" if mix_info_key in post and mix_id_key in post[mix_info_key] else "no",
            "4CAT_first_video_displayed": "yes" if displayed else "no",
            # other videos may have been viewed, but this is unknown to us
            "collection_id": post.get(mix_info_key, {}).get(mix_id_key, "N/A"),
            "collection_name": post.get(mix_info_key, {}).get(mix_name_key, "N/A"),
            "place_in_collection": mix_current_episode,
            "unix_timestamp": int(post_timestamp.timestamp()),
        }

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
