"""
Imports 4plebs database dumps
"""
import json
import csv
import re

from csv import DictReader
from lib.logger import Logger
from lib.database import Database


def parse_value(value):
    """
    The csv data is a little peculiar, strip some useless values

    :param value:  Value to process
    :return:  Parsed value
    """
    if value == "\\N":
        return ""

    try:
        if "\n" in value:
            return value.replace("\\\n", "\n")
    except TypeError:
        pass

    return value


class fourplebs(csv.Dialect):
    """
    CSV Dialect as used in 4plebs database dumps - to be used with Python CSV functions
    """
    delimiter = ","
    doublequote = False
    escapechar = "\\"
    lineterminator = "\n"
    quotechar = '"'
    quoting = csv.QUOTE_ALL
    skipinitialspace = False
    strict = True


# column names as described by 4plebs
columns = ["num", "subnum", "thread_num", "op", "timestamp", "timestamp_expired", "preview_orig", "preview_w",
           "preview_h", "media_filename", "media_w", "media_h", "media_size", "media_hash", "media_orig", "spoiler",
           "deleted", "capcode", "email", "name", "trip", "title", "comment", "sticky", "locked", "poster_hash",
           "poster_country", "exif"]

# todo: extract these from commandline arguments
csvfile = "trv.csv"
board = "trv"

# init database - we need the thread data to know whether to insert a new thread for a post
db = Database(logger=Logger())
threads = {thread["id"]: thread for thread in
           db.fetchall("SELECT id, timestamp, timestamp_modified, post_last FROM threads")}

# start parsing
with open(csvfile) as csvdump:
    reader = DictReader(csvdump, fieldnames=columns, dialect=fourplebs)
    posts_added = 0

    for post in reader:
        # sanitize post data
        post = dict(post)
        post = {key: parse_value(post[key]) for key in post}
        post = {key: post[key].strip() if post[key] != None else post[key] for key in post}
        post = {key: "" if post[key] == "N" and key not in ["comment", "name"] else post[key] for key in post}

        # see what we need to do with the thread
        post_thread = post["num"] if post["thread_num"] == 0 else post["thread_num"]
        if post_thread in threads.keys():
            # thread already exists

            thread = threads[post_thread]
            updates = {}
            if int(post["timestamp"]) < int(thread["timestamp"]):
                updates["timestamp"] = post["timestamp"]

            if int(post["timestamp"]) > int(thread["timestamp_modified"]):
                updates["timestamp_modified"] = post["timestamp"]

            if post["num"] > thread["post_last"]:
                updates["post_last"] = post["num"]

            # not part of the dump:
            # unique_ips, replies, images, bumplimit, imagelimit
            # some of these could be derived later

            if post["sticky"] == "1":
                updates["is_sticky"] = True

            if post["locked"] == "1":
                updates["is_closed"] = True

            # only update database if something actually changed
            if updates != {}:
                db.update("threads", where={"id": thread["id"]}, data=updates, commit=False)
                threads[post_thread] = {**thread, **updates}

        else:
            # insert new thread
            thread_data = {
                "id": post_thread,
                "board": board,
                "timestamp": post["timestamp"],
                "timestamp_scraped": 0,
                "timestamp_modified": 0,
                "post_last": post["num"],
                "index_positions": ""
            }

            db.insert("threads", data=thread_data, commit=False)
            threads[post_thread] = thread_data

        # add post to database
        db.insert("posts", data={
            "id": post["num"],
            "timestamp": post["timestamp"],
            "thread_id": post_thread,
            "body": post["comment"],
            "author": post["name"],
            "author_type_id": post["capcode"],
            "author_trip": post["trip"],
            "subject": post["title"],
            "country_code": post["poster_country"],
            "image_file": post["media_filename"],
            "image_4chan": post["media_orig"],
            "image_md5": post["media_hash"],
            "image_dimensions": json.dumps({"w": post["media_w"], "h": post["media_h"]}) if post[
                                                                                                "media_filename"] != "" else "",
            "image_filesize": post["media_size"],
            "semantic_url": "",
            "is_deleted": False,
            "unsorted_data": "{}"
        }, safe=True, commit=False)

        posts_added += 1

        # add links to other posts
        if post["comment"] != "":
            links = re.findall(">>([0-9]+)", post["comment"])
            for linked_post in links:
                db.insert("posts_mention", data={"post_id": post["num"], "mentioned_id": linked_post}, commit=False)

        if posts_added % 1000 == 0:
            print("Processed %i posts." % posts_added)

        # for speed, we only commit every so many posts
        if posts_added % 10000 == 0:
            print("Committing posts %i-%i to database" % (posts_added - 10000, posts_added))
            db.commit()

print("Done! Committing final transaction...")
db.commit()
print("Done!")

# update thread stats that we can derive ourselves
print("Updating thread statistics...")
threads_updated = 0
for thread in threads:
    posts = db.fetchone("SELECT COUNT(*) AS num FROM posts WHERE thread_id = %s", (thread,))["num"]
    images = db.fetchone("SELECT COUNT(*) AS num FROM posts WHERE image_file != '' AND thread_id = %s", (thread,))["num"]

    db.update("threads", data={"num_replies": posts - 1, "num_images": images}, where={"id": thread}, commit=False)

    threads_updated += 1
    if threads_updated % 1000 == 0:
        print("Updated threads %i-%i of %i" % (threads_updated - 1000, threads_updated, len(threads)))

# finalize last bits
print("Committing changes...")
db.commit()
print("Done!")