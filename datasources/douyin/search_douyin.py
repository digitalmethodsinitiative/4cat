"""
Import scraped Douyin data
"""
import urllib
from datetime import datetime

from backend.abstract.search import Search


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
        post_timestamp = datetime.fromtimestamp(post["create_time"])

        metadata = post.get("__import_meta")

        videos = sorted([vid for vid in post["video"]["bit_rate"]], key=lambda d: d.get("bit_rate"),
                        reverse=True)

        return {
            "id": post["aweme_id"],
            "thread_id": post["group_id"],
            "subject": "",
            "body": post["desc"],
            "timestamp": post_timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "post_source_domain": urllib.parse.unquote(metadata.get("source_platform_url")),  # Adding this as different Douyin pages contain different data
            "post_url": f"https://www.douyin.com/video/{post['aweme_id']}",
            "region": post.get("region"),
            "hashtags": ",".join([item["hashtag_name"] for item in (post["text_extra"] if post["text_extra"] is not None else []) if "hashtag_name" in item]),
            "mentions": ",".join([f"https://www.douyin.com/user/{item['sec_uid']}" for item in (post["text_extra"] if post["text_extra"] is not None else []) if "sec_uid" in item]),  # Actual username does not appear in object, but the sec_uid can be used to form a link to their profile
            "video_tags": ",".join([item["tag_name"] for item in (post["video_tag"] if post["video_tag"] is not None else []) if "tag_name" in item]),  # unsure exactly what this is, but some videos have them
            "prevent_download": ("yes" if post["prevent_download"] else "no") if "prevent_download" in post else None,
            "video_url": videos[0]["play_addr"].get("url_list", [''])[-1] if len(videos) > 0 else "",  # This URL seems to work depending on the referrer (i.e., cut and paste into a browser will work, but not as a link)
            "video_duration": post["duration"] if "duration" in post else post["video"].get("duration"),
            # Video stats
            "collect_count": post["statistics"].get("collect_count", 0),
            "comment_count": post["statistics"].get("comment_count", 0),
            "digg_count": post["statistics"].get("digg_count", 0),
            "download_count": post["statistics"].get("download_count", 0),
            "forward_count": post["statistics"].get("forward_count", 0),
            "play_count": post["statistics"].get("play_count", 0),
            "share_count": post["statistics"].get("share_count", 0),
            # Author data
            "author_user_id": post["author_user_id"],
            "author_nickname": post["author"]["nickname"],
            "author_profile_url": f"https://www.douyin.com/user/{post['author']['sec_uid']}",
            "author_thumbnail_url": post["author"]["avatar_thumb"].get("url_list", [''])[0],
            "author_region": post["author"].get("region"),
            "author_is_ad_fake": post["author"].get("is_ad_fake"),
            # Collection/Mix
            "part_of_collection": "yes" if "mix_info" in post else "no",
            "collection_id": post.get("mix_info", {}).get("mix_id", "N/A"),
            "collection_name": post.get("mix_info", {}).get("mix_name", "N/A"),
            "place_in_collection": post.get("mix_info", {}).get("statis", {}).get("current_episode", "N/A"),
            "unix_timestamp": int(post_timestamp.timestamp()),
        }
