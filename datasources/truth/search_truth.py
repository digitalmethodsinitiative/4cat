"""
Import scraped Truth Social data
"""
import datetime

from backend.lib.search import Search
from common.lib.item_mapping import MappedItem


class SearchGab(Search):
    """
    Import scraped truth social data
    """
    type = "truthsocial-search"  # job ID
    category = "Search"  # category
    title = "Import scraped Truth Social data"  # title displayed in UI
    description = "Import Truth Social data collected with an external tool such as Zeeschuimer."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_from_zeeschuimer = True
    fake = ""

    # not available as a processor for existing datasets
    accepts = [None]

    def get_items(self, query):
        """
        Run custom search

        Not available for Truth Social
        """
        raise NotImplementedError("Truth Social datasets can only be created by importing data from elsewhere")

    @staticmethod
    def map_item(post):
        """
        Parse Truth Social post

        :param node:  Data as received from Truth Social
        :return dict:  Mapped item
        """
        errors = []
        post_time = datetime.datetime.strptime(post["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
        images = []
        videos = []
        video_thumbs = []
        if "media_attachments" in post:
            for media in post["media_attachments"]:
                mtype = media.get("type")
                if mtype == "image":
                    images.append(media.get("url"))
                elif mtype == "video":
                    videos.append(media.get("url"))
                    video_thumbs.append(media.get("preview_url"))
                elif mtype == "tv":
                    # Truth social has "TV channels" with videos
                    # These do not have direct links to media
                    # url is a thumbnail
                    video_thumbs.append(media.get("url"))
                    # preview_url is a smaller thumb
                else:
                    errors.append(f"New media type: {mtype}")

        group = post.get("group") if post.get("group") else {}
        
        if post.get("quote_id", None):
            thread_id = post.get("quote_id")
        elif post.get("in_reply_to", None):
            reply_to = post.get("in_reply_to")
            while reply_to:
                if reply_to.get("in_reply_to", None):
                    reply_to = reply_to.get("in_reply_to")
                else:
                    thread_id = reply_to.get("id")
                    break
        else:
            thread_id = post.get("id")
        
        mentions = [mention.get("username") for mention in (post.get("mentions") if post.get("mentions") else [])]
        hashtags = [tag.get("name") for tag in (post.get("tags") if post.get("tags") else [])]
    
        mapped_item = {
            "id": post["id"],
            "created_at": post["created_at"],
            "body": post["content"],
            "url": post.get("url", None),
            "reblogs_count": post.get("reblogs_count", 0),
            "replies_count": post.get("replies_count", 0),

            "account_id": post["account"]["id"],
            "account_username": post["account"]["username"],
            "account_display_name": post["account"]["display_name"],
            "account_avatar": post["account"]["avatar"],
            "account_verified": post["account"]["verified"],
            "account_followers": post["account"]["followers_count"],
            "account_following": post["account"]["following_count"],
            
            "mentions": ",".join(mentions),
            "hashtags": ",".join(hashtags),

            # media
            "images": ",".join(images),
            "video_thumbs": ",".join(video_thumbs),
            "video_urls": ",".join(videos),
            
            # group
            "group_id": group.get("id", None),
            "group_display_name": group.get("display_name", None),
            "group_avatar": group.get("avatar", None),
            "group_note": group.get("note", None),
            "group_members_count": group.get("members_count", 0),

            "thread_id": thread_id,
            "timestamp": post_time.strftime("%Y-%m-%d %H:%M:%S")
        }        

        return MappedItem(mapped_item, message="; ".join(errors))