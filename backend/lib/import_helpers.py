"""
Helper methods and classes for dump importer (see importDump.py)
"""
import json
import csv
import re

link_regex = re.compile(">>([0-9]+)")


def parse_value(key, value):
    """
    The csv data is a little peculiar, strip some useless values

    :param value:  Value to process
    :return:  Parsed value
    """
    if isinstance(value, str):
        value = value.strip()

    if value == "N" and key not in ["comment", "name", "title"]:
        return ""

    try:
        if "\n" in value:
            return value.replace("\\\n", "\n")
    except TypeError:
        pass

    return value


def process_post(post, db, sequence, threads, board):
    """
    Add one post to the database

    :param dict post:  Post data
    :param Database db:  Database handler
    :param tuple sequence: tuple(posts to skip, number of posts added)
    :param int posts_added:   Posts added so far
    :param dict threads: Thread info, {id: data}
    :return:
    """
    # skip if needed
    posts_added = sequence[1] + 1
    if posts_added <= sequence[0]:
        return posts_added

    # sanitize post data
    post = dict(post)
    post = {key: parse_value(key, post[key]) for key in post}

    # see what we need to do with the thread
    post_thread = post["num"] if post["thread_num"] == 0 else post["thread_num"]
    post_thread = int(post_thread)

    if post_thread in threads:
        # thread already exists

        thread = threads[post_thread]
        updates = {}
        if int(post["timestamp"]) < int(thread["timestamp"]):
            updates["timestamp"] = post["timestamp"]

        if int(post["timestamp"]) > int(thread["timestamp_modified"]):
            updates["timestamp_modified"] = post["timestamp"]

        if int(post["num"]) > int(thread["post_last"]):
            updates["post_last"] = post["num"]

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
        "timestamp_deleted": post["deleted"] if int(post["deleted"]) > 1 else 0,
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
        "unsorted_data": "{}"
    }, safe=True, commit=False)

    # add links to other posts
    if post["comment"] and isinstance(post["comment"], str):
        links = re.findall(link_regex, post["comment"])
        for linked_post in links:
            if len(str(linked_post)) <= 15:
                db.insert("posts_mention", data={"post_id": post["num"], "mentioned_id": linked_post}, commit=False)

    if posts_added % 1000 == 0:
        print("Processed %i posts." % posts_added)

    # for speed, we only commit every so many posts
    if posts_added % 10000 == 0:
        print("Committing posts %i-%i to database" % (posts_added - 10000, posts_added))
        db.commit()

    return posts_added


class FourPlebs(csv.Dialect):
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

    columns = ["num", "subnum", "thread_num", "op", "timestamp", "timestamp_expired", "preview_orig", "preview_w",
               "preview_h", "media_filename", "media_w", "media_h", "media_size", "media_hash", "media_orig", "spoiler",
               "deleted", "capcode", "email", "name", "trip", "title", "comment", "sticky", "locked", "poster_hash",
               "poster_country", "exif"]
