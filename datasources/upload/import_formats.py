import datetime
import json
import csv
import re

from dateutil.parser import parse as parse_datetime
from common.lib.exceptions import ProcessorException


class InvalidCustomFormat(ProcessorException):
    """
    Raise if processor throws an exception
    """
    pass


class InvalidImportedItem:
    """
    Generic data class to pass to have the importer recognise an item as
    one that should not be written to the result CSV file
    """
    reason = ""

    def __init__(self, reason=""):
        self.reason = reason


def import_crowdtangle_instagram(reader, columns, dataset, parameters):
    """
    Import an export of a CrowdTangle Instagram list

    :param csv.DictReader reader:  Reader object of input file
    :param Iterable columns:  Required columns
    :param DataSet dataset:  Dataset to import into
    :param dict parameters:  Dataset parameters
    :return tuple:  Items written, items skipped
    """
    # write to the result file
    hashtag = re.compile(r"#([^\s,.+=-]+)")
    usertag = re.compile(r"@([^\s,.+=-]+)")
    for item in reader:
        url = item["URL"]
        url = re.sub(r"/*$", "", url)

        post_id = url.split("/")[-1]
        caption = item["Description"]
        hashtags = hashtag.findall(caption)
        usertags = usertag.findall(caption)

        datestamp = " ".join(item["Post Created"].split(" ")[:-1])
        date = datetime.datetime.strptime(datestamp, "%Y-%m-%d %H:%M:%S")

        item = {
            "id": post_id,
            "thread_id": post_id,
            "parent_id": post_id,
            "body": caption if caption is not None else "",
            "author": item["User Name"],
            "timestamp": date.strftime('%Y-%m-%d %H:%M:%S'),
            "unix_timestamp": int(date.timestamp()),
            "type": "picture" if item["Type"] == "Photo" else item["Type"].lower(),
            "url": item["URL"],
            "thumbnail_url": item["Photo"],
            "hashtags": ",".join(hashtags),
            "usertags": ",".join(usertags),
            "mentioned": "",
            "num_likes": item["Likes"],
            "num_comments": item["Comments"],
            "subject": item["Title"]
        }

        yield item


def import_crowdtangle_facebook(reader, columns, dataset, parameters):
    """
    Import an export of a CrowdTangle Facebook list

    :param csv.DictReader reader:  Reader object of input file
    :param Iterable columns:  Required columns
    :param DataSet dataset:  Dataset to import into
    :param dict parameters:  Dataset parameters
    :return tuple:  Items written, items skipped
    """
    # write to the result file
    hashtag = re.compile(r"#([^\s,.+=-]+)")
    entity_name = "Page Name" if "Page Name" in reader.fieldnames else "Group Name"
    overperforming_column = None
    for item in reader:
        hashtags = hashtag.findall(item["Message"])
        try:
            date = datetime.datetime.strptime(" ".join(item["Post Created"].split(" ")[:2]), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            yield InvalidImportedItem(reason=f"Cannot parse date/time '{item['Post Created']}'; skipping post")

        is_from_elsewhere = item["Link"].find("https://www.facebook.com/" + item["User Name"]) < 0
        shared_page = item["Link"].split("/")[3] if is_from_elsewhere and item["Link"].find(
            "https://www.facebook.com/") == 0 else ""

        # this one is a handful
        # unicode in csv column names is no fun
        if not overperforming_column:
            overperforming_column = [c for c in item.keys() if "Overperforming" in c][0]

        overperforming = item.get(overperforming_column, "")

        item = {
            "id": item["URL"].split("/")[-1],
            "thread_id": item["URL"].split("/")[-1],
            "body": item["Message"],
            "author": item["User Name"],
            "timestamp": date.strftime('%Y-%m-%d %H:%M:%S'),
            "unix_timestamp": int(date.timestamp()),
            "page_name": item[entity_name],
            "page_category": item["Page Category"],
            "page_top_country": item["Page Admin Top Country"],
            "page_description": item["Page Description"],
            "page_created": item["Page Created"],
            "page_likes": item["Likes at Posting"],
            "page_id": item["Facebook Id"],
            "page_followers": item["Followers at Posting"],
            "page_shared_from": shared_page,
            "type": item["Type"],
            "interactions": int(re.sub(r"[^0-9]", "", item["Total Interactions"])) if item[
                "Total Interactions"] else 0,
            "comments": item["Comments"],
            "shares": item["Shares"],
            "likes": item["Likes"],
            "likes_love": item["Love"],
            "likes_wow": item["Wow"],
            "likes_haha": item["Haha"],
            "likes_sad": item["Sad"],
            "likes_angry": item["Angry"],
            "likes_care": item["Care"],
            "views_post": item["Post Views"],
            "views_total": item["Total Views"],
            "views_total_crossposts": item["Total Views For All Crossposts"],
            "overperforming_score": overperforming,
            "video_length": "" if item["Video Length"] == "N/A" else item["Video Length"],
            "video_status": item["Video Share Status"],
            "video_own": "yes" if item["Is Video Owner?"] == "Yes" else "no",
            "url": item["URL"],
            "hashtags": ",".join(hashtags),
            "url_original": item["Final Link"] if item["Final Link"] else item["Link"],
            "body_image": item["Image Text"],
            "body_link": item["Link Text"],
            "body_description": item["Description"],
            "sponsor_id": item["Sponsor Id"],
            "sponsor_name": item["Sponsor Name"],
            "sponsor_category": item["Sponsor Category"]
        }

        yield item


def import_facepager(reader, columns, dataset, parameters):
    """
    Import an export of a Facepager export

    :param csv.DictReader reader:  Reader object of input file
    :param Iterable columns:  Required columns
    :param DataSet dataset:  Dataset to import into
    :param dict parameters:  Dataset parameters
    :return tuple:  Items written, items skipped
    """
    # write to the result file
    for item in reader:
        hashtags = json.loads(item["hashtags"])
        hashtags = [hashtag["name"] for hashtag in hashtags]

        item = {
            "id": item["id"],
            "thread_id": item["id"],
            "author": item["authorMeta.name"],
            "body": item["text"],
            "timestamp": datetime.datetime.utcfromtimestamp(int(item["createTime"])).strftime(
                '%Y-%m-%d %H:%M:%S'),
            "unix_timestamp": int(item["createTime"]),
            "is_harmful": -1,
            "is_duet": -1,
            "music_name": item["musicMeta.musicName"],
            "music_id": item["musicMeta.musicId"],
            "music_author": item["musicMeta.musicAuthor"],
            "video_url": item["videoUrl"],
            "tiktok_url": "https://tiktok.com/@%s/video/%s" % (item["authorMeta.id"], item["id"]),
            "thumbnail_url": item["covers.default"],
            "amount_likes": item["diggCount"],
            "amount_comments": item["commentCount"],
            "amount_shares": item["shareCount"],
            "amount_plays": item["playCount"],
            "hashtags": ",".join(hashtags)
        }

        yield item


def import_ytdt_videolist(reader, columns, dataset, parameters):
    """
    Import an export of a YouTube Data Tools Video List export

    :param csv.DictReader reader:  Reader object of input file
    :param Iterable columns:  Required columns
    :param DataSet dataset:  Dataset to import into
    :param dict parameters:  Dataset parameters
    :return tuple:  Items written, items skipped
    """
    # write to the result file
    for item in reader:
        try:
            date = datetime.datetime.strptime(item["publishedAt"], "%Y-%m-%dT%H:%M:%SZ")  # ex. 2022-11-11T05:30:01Z
        except ValueError:
            yield InvalidImportedItem(reason=f"Invalid date ({item['publishedAt']})")
            continue

        collection_date = "_".join(dataset.parameters.get("filename").split("_")[2:]).replace(".csv", "")

        item = {
            "id": item.get('videoId'),
            "thread_id": item.get('channelId'),
            "author": item.get('channelTitle'),
            "body": item.get('videoDescription'),
            "timestamp": date.strftime('%Y-%m-%d %H:%M:%S'),
            "unix_timestamp": int(date.timestamp()),
            **item,
            "source_filename": dataset.parameters.get("filename"),
            "date_collected": collection_date,
            "youtube_url": f"https://www.youtube.com/watch?v={item['videoId']}"
        }

        yield item


def import_ytdt_commentlist(reader, columns, dataset, parameters):
    """
    Import an export of a YouTube Data Tools Video Info export

    :param csv.DictReader reader:  Reader object of input file
    :param Iterable columns:  Required columns
    :param DataSet dataset:  Dataset to import into
    :param dict parameters:  Dataset parameters
    :return tuple:  Items written, items skipped
    """
    # write to the result file
    for item in reader:
        try:
            date = datetime.datetime.strptime(item["publishedAt"], "%Y-%m-%d %H:%M:%S")  # ex. 2022-11-11 05:30:01
        except ValueError:
            yield InvalidImportedItem(reason=f"Invalid date ({item['publishedAt']})")
            continue

        collection_date = "_".join(dataset.parameters.get("filename").split("_")[2:]).replace(".csv", "")

        item = {
            "id": item["id"],
            "thread_id": item["isReplyTo"] if item["isReplyTo"] else item["id"],
            "author": item["authorName"],
            "body": item["text"],
            "timestamp": date.strftime('%Y-%m-%d %H:%M:%S'),
            "unix_timestamp": int(date.timestamp()),
            **item,
            "source_filename": dataset.parameters.get("filename"),
            "date_collected": collection_date,
        }

        yield item


def import_bzy_weibo(reader, columns, dataset, parameter):
    """
    Import Weibo item collected by Bazhuayu

    :param csv.DictReader reader:  Reader object of input file
    :param Iterable columns:  Required columns
    :param DataSet dataset:  Dataset to import into
    :param dict parameters:  Dataset parameters
    :return tuple:  Items written, items skipped
    """
    index = 1
    year = datetime.datetime.now().year

    for item in reader:
        if "from1" not in item:
            raise InvalidCustomFormat("CSV does not appear to be Bazhuayu format for Sina Weibo; please try importing again with CSV format set to \"Custom/other\".")
        raw_timestamp = item["from1"].strip()
        timestamp_bits = re.split(r"[年月日\s:]+", raw_timestamp)

        if re.match(r"[0-9]{2}月[0-9]{2}日 [0-9]{2}:[0-9]{2}", raw_timestamp):
            timestamp = datetime.datetime(year, int(timestamp_bits[0]), int(timestamp_bits[1]), int(timestamp_bits[2]),
                                          int(timestamp_bits[3]))
        elif re.match(r"[0-9]{4}[0-9]{2}月[0-9]{2}日 [0-9]{2}:[0-9]{2}", raw_timestamp):

            timestamp = datetime.datetime(int(timestamp_bits[0]), int(timestamp_bits[1]), int(timestamp_bits[2]),
                                          int(timestamp_bits[3]), int(timestamp_bits[4]))
        else:
            yield InvalidImportedItem(f"Cannot parse timestamp {raw_timestamp}")

        item = {
            "id": index,
            "thread_id": index,
            "author": item["标题"],
            "body": item["txt"],
            "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "image_url": item["图片"],
            **item,
            "unix_timestamp": int(timestamp.timestamp())
        }

        index += 1
        yield item


def map_csv_items(reader, columns, dataset, parameters):
    """
    Read CSV items and put them in the 4CAT dataset file

    This version of the method mostly just copies the file, applying the
    supplied mapping where possible. It could alternatively apply more
    fancy mappings.

    :param csv.DictReader reader:  Reader object of input file
    :param Iterable columns:  Required columns
    :param DataSet dataset:  Dataset to import into
    :param dict parameters:  Dataset parameters
    :return tuple:  Items written, items skipped
    """
    # write to the result file
    indexes = {}
    for row in reader:
        mapped_row = {}
        for field in columns:
            mapping = parameters.get("mapping-" + field)
            if mapping:
                if mapping == "__4cat_auto_sequence":
                    # auto-numbering
                    if field not in indexes:
                        indexes[field] = 1
                    mapped_row[field] = indexes[field]
                    indexes[field] += 1
                else:
                    # actual mapping
                    mapped_row[field] = row[mapping]

        # ensure that timestamp is YYYY-MM-DD HH:MM:SS and that there
        # is a unix timestamp. this will override the columns if they
        # already exist! but it is necessary for 4CAT to handle the
        # data in processors etc and should be an equivalent value.
        try:
            if mapped_row["timestamp"].isdecimal():
                timestamp = datetime.datetime.fromtimestamp(float(mapped_row["timestamp"]))
            else:
                timestamp = parse_datetime(mapped_row["timestamp"])

            mapped_row["timestamp"] = timestamp.strftime("%Y-%m-%d %H:%M:%S")
            mapped_row["unix_timestamp"] = int(timestamp.timestamp())

            # this ensures that the required columns are always the first
            # columns, and the rest is in original order
            for field, value in row.items():
                if field not in mapped_row and field:
                    mapped_row[field] = value

        except (ValueError, OSError, AttributeError):
            # skip rows without a valid timestamp - this may happen
            # despite validation because only a sample is validated
            # this is an OSError on Windows sometimes???
            yield InvalidImportedItem()
            continue

        yield mapped_row


# tools that are supported for importing
# defined here (instead of at the top) so we can refer to the functions
# defined above
# format: dictionary with keys name, columns, mapper
# name is a human-readable name for this format (e.g. a tool name)
# columns is a set of required columns in the uploaded csv
# mapper is a function that writes the 4CAT-compatible CSV
tools = {
    "instagram-crowdtangle": {
        "name": "Instagram (via CrowdTangle export)",
        "columns": {"Account", "User Name", "Followers at Posting", "Post Created", "Type", "Likes", "Comments",
                    "Views", "URL", "Link", "Photo", "Title", "Description"},
        "mapper": import_crowdtangle_instagram
    },
    "facebook-crowdtangle": {
        "name": "Facebook (via CrowdTangle export)",
        "columns": {"Page Name", "User Name", "Facebook Id", "Page Category", "Page Admin Top Country",
                    "Page Description", "Page Created", "Likes at Posting", "Followers at Posting", "Post Created",
                    "Post Created Date", "Post Created Time", "Type", "Total Interactions", "Likes", "Comments",
                    "Shares", "Love", "Wow", "Haha", "Sad", "Angry", "Care", "Video Share Status",
                    "Is Video Owner?", "Post Views", "Total Views", "Total Views For All Crossposts",
                    "Video Length", "URL", "Message", "Link", "Final Link", "Image Text", "Link Text",
                    "Description", "Sponsor Id", "Sponsor Name", "Sponsor Category"},
        "mapper": import_crowdtangle_facebook
    },
    "facepager": {
        "name": "Facebook (via Facepager export)",
        "columns": {"path", "id", "parent_id", "level", "object_id", "object_type", "query_status", "query_time",
                    "query_type", "from.name", "created_time", "type", "link", "picture", "full_picture", "",
                    "comments.summary.total_count", "shares.count", "reactions.summary.total_count",
                    "like.summary.total_count", "love.summary.total_count", "haha.summary.total_count",
                    "wow.summary.total_count", "sad.summary.total_count", "angry.summary.total_count", "message"},
        "mapper": import_facepager
    },
    "youtube_video_list": {
        "name": "YouTube videos (via YouTube Data Tools' Video List module)",
        "columns": {"publishedAt", "videoId", "channelId", "channelTitle", "videoDescription"},
        "mapper": import_ytdt_videolist,
        "csv_dialect": {"doublequote": True, "escapechar": "\\"},
    },
    "youtube_comment_list": {
        "name": "YouTube comments (via YouTube Data Tools' Video Info module)",
        "columns": {"id", "isReplyTo", "authorName", "text", "publishedAt"},
        "mapper": import_ytdt_commentlist,
        "csv_dialect": {"doublequote": True, "escapechar": "\\"},
    },
    "bazhuayu_weibo": {
        "name": "Sina Weibo (via Bazhuayu)",
        "columns": {},
        "mapper": import_bzy_weibo
    },
    "custom": {
        "name": "Custom/other",
        "columns": {
            "id": "A value that uniquely identifies the item, like a numerical ID.",
            "thread_id": "A value that uniquely identifies the sub-collection an item is a part of, e.g. a forum "
                         "thread. If this does not apply to your dataset you can use the same value as for 'id' "
                         "here.",
            "author": "A value that identifies the author of the item. If the option to pseudonymise data is "
                      "selected below, this field will be pseudonymised.",
            "body": "The 'content' of the item, e.g. a post's text.",
            "timestamp": "The time the item was made or posted. 4CAT will try to interpret this value, but for the "
                         "best results use YYYY-MM-DD HH:MM:SS notation."
        },
        "mapper": map_csv_items,
        "allow_user_mapping": True
    }
}
