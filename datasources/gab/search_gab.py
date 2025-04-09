"""
Import scraped Gab data
"""
import datetime

from backend.lib.search import Search
from common.lib.item_mapping import MappedItem, MissingMappedField


class SearchGab(Search):
    """
    Import scraped gab data
    """
    type = "gab-search"  # job ID
    category = "Search"  # category
    title = "Import scraped Gab data"  # title displayed in UI
    description = "Import Gab data collected with an external tool such as Zeeschuimer."  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_from_zeeschuimer = True
    fake = ""

    # not available as a processor for existing datasets
    accepts = [None]

    def get_items(self, query):
        """
        Run custom search

        Not available for Gab
        """
        raise NotImplementedError("Gab datasets can only be created by importing data from elsewhere")

    @staticmethod
    def map_item(post):
        """
        Parse Gab post

        :param node:  Data as received from Gab
        :return dict:  Mapped item
        """
        unknown_data = []
        post_id = post.get("i", post["id"])
        metadata = post.get("__import_meta", {})
        timestamp_collected = datetime.datetime.fromtimestamp(metadata.get("timestamp_collected")/1000).strftime("%Y-%m-%d %H:%M:%S") if metadata.get("timestamp_collected") else MissingMappedField("Unknown")
        # reaction_type seems to just be nummeric keys; unsure which reactions they map to
        reactions =  post.get("rc", post.get("reactions_counts"))
        if type(reactions) != int:
            reaction_count = sum([reaction_value for reaction_type, reaction_value in post.get("rc", post.get("reactions_counts")).items()])
        else:
            reaction_count = reactions

        # Other dictionaries are nested in the post dictionary
        group = post.get("g", post.get("group", {}))
        author = post.get("author_info", post.get("account", {}))
        mentions = post.get("m", post.get("mentions", []))
        tags = post.get("tg", post.get("tags", []))
        # card or link
        card = post.get("card", post.get("link", {}))
        # media or image_info
        media_items = post.get("image_info", post.get("media_attachments", []))
        image_urls = [media.get("u", media.get("url")) for media in media_items if media.get("t", media.get("type")) == "image"]
        video_urls = [media.get("smp4", media.get("source_mp4")) for media in media_items if media.get("t", media.get("type")) == "video"]
        if any([media_type not in ["image", "video"] for media_type in [media.get("t", media.get("type")) for media in media_items]]):
            unknown_data.extend([f"Unknown media type: {media}" for media in media_items if media.get('t', media.get('type')) not in ['image', 'video']])
        if any([True for vid in video_urls if vid is None]) or any([True for img in image_urls if img is None]):
            unknown_data.extend([f"Media missing URL: {img}" for img in image_urls if img is None])
            unknown_data.extend([f"Media missing URL: {vid}" for vid in video_urls if vid is None])
            # remove None values from the lists
            image_urls = [img for img in image_urls if img is not None]
            video_urls = [vid for vid in video_urls if vid is not None]
        
        post_time = datetime.datetime.strptime(post.get("ca", post.get("created_at")), "%Y-%m-%dT%H:%M:%S.%fZ")
        mapped_item = {
            "collected_at": timestamp_collected,
            "source_url": metadata.get("source_platform_url", MissingMappedField("Unknown")), # URL from which post was collected
            "id": post_id,
            "created_at": post_time.strftime("%Y-%m-%d %H:%M:%S"),
            "body": post.get("c") if "c" in post else post["content"],
            "url": post.get("ul") if "ul" in post else post["url"],
            "reaction_count": reaction_count,
            "favourites_count": post.get("fbc", post.get("favourites_count")),
            "replies_count": post.get("rc", post.get("replies_count")),
            "reblogs_count": post.get("rbc", post.get("reblogs_count")),
            "mentions": ",".join([mention["username"] for mention in mentions]),
            "tags": ",".join([tag["name"] for tag in tags]),	

            "group_id": group["id"] if group else None,
            "group_title": group["title"] if group else None,
            "group_description": group["description"] if group else None,
            "group_member_count": group["member_count"] if group else None,
            "group_is_private": group["is_private"] if group else None,
            "group_url": group["url"] if group else None,
            "group_created_at": group.get("created_at") if group else None,

            "account_id": author.get("i") if "i" in author else author["id"],
            "account_username": author.get("un") if "un" in author else author["username"],
            "account_account": author.get("ac") if "ac"in author else author["acct"],
            "account_display_name": author.get("dn") if "dn" in author else author["display_name"],
            "account_note": author.get("nt") if "nt" in author else author["note"],

            "link_id": card["id"] if card else None,
            "link_url": card["url"] if card else None,
            "link_title": card["title"] if card else None,
            "link_description": card["description"] if card else None,
            "link_type": card["type"] if card else None,
            "link_image": card["image"] if card else None,

            "image_urls": ",".join(image_urls),
            "video_urls": ",".join(video_urls),

            "thread_id": post.get("i") if "i" in post else post["conversation_id"],
            "timestamp": post_time.strftime("%Y-%m-%d %H:%M:%S")
        }        
    
        return MappedItem(mapped_item, message="".join(unknown_data)) if unknown_data else MappedItem(mapped_item)
