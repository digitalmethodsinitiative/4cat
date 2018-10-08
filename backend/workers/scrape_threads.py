"""
Thread scraper

Parses 4chan API data, saving it to database and queueing downloads
"""
import hashlib
import os.path
import base64
import json
import re

from lib.scraper import BasicJSONScraper
from lib.queue import JobAlreadyExistsException

import config


class ThreadScraper(BasicJSONScraper):
    """
    Scrape 4chan threads

    This scrapes individual threads, and saves the posts into the database.
    """
    type = "thread"
    max_workers = 2
    pause = 2

    # for new posts, any fields not in here will be saved in the "unsorted_data" column for that post as part of a
    # JSONified dict
    known_fields = ["no", "resto", "sticky", "closed", "archived", "archived_on", "now", "time", "name", "trip", "id",
                    "capcode", "country", "country_name", "sub", "com", "tim", "filename", "ext", "fsize", "md5", "w",
                    "h", "tn_w", "tn_h", "filedeleted", "spoiler", "custom_spoiler", "omitted_posts", "omitted_images",
                    "replies", "images", "bumplimit", "imagelimit", "capcode_replies", "last_modified", "tag",
                    "semantic_url", "since4pass", "unique_ips"]

    # these fields should be present for every single post, and if they're not something weird is going on
    required_fields = ["no", "resto", "now", "time"]
    required_fields_op = ["no", "resto", "now", "time", "replies", "images"]

    def process(self, data):
        """
        Process scraped thread data

        Adds new posts to the database, updates thread info, and queues images
        for downloading.

        :param dict data: The thread data, as parsed JSON data
        """
        if "posts" not in data or not data["posts"]:
            self.log.warning(
                "JSON response for thread %s contained no posts, could not process" % self.job["remote_id"])
            return

        # check if OP has all the required data
        first_post = data["posts"][0]
        missing = set(self.required_fields_op) - set(first_post.keys())
        if missing != set():
            self.log.warning("OP is missing required fields %s, ignoring" % repr(missing))
            return

        thread = self.update_thread(first_post, last_reply=max([post["time"] for post in data["posts"]]),
                                    last_post=max([post["no"] for post in data["posts"]]))

        if not thread:
            return

        # create a dict mapped as `post id`: `post data` for easier comparisons with existing data
        post_dict_scrape = {post["no"]: post for post in data["posts"]}
        post_dict_db = {post["id"]: post for post in
                        self.db.fetchall("SELECT * FROM posts WHERE thread_id = %s AND timestamp_deleted = 0",
                                         (first_post["no"],))}

        # mark deleted posts as such
        deleted = set(post_dict_db.keys()) - set(post_dict_scrape.keys())
        for post_id in deleted:
            # print("Post deleted: %s" % repr(post_dict_db[post_id]))
            self.db.update("posts", where={"id": post_id}, data={"timestamp_deleted": self.loop_time}, commit=False)
        self.db.commit()

        # add new posts
        new = set(post_dict_scrape.keys()) - set(post_dict_db.keys())
        new_posts = 0
        for post_id in new:
            post = post_dict_scrape[post_id]

            # check for data integrity
            missing = set(self.required_fields) - set(post.keys())
            if missing != set():
                self.log.warning("Missing fields %s in scraped post, ignoring" % repr(missing))
                continue

            # save dimensions as a dumpable dict - no need to make it indexable
            dimensions = {"w": post["w"], "h": post["h"], "tw": post["tn_w"],
                          "th": post["tn_h"]} if "w" in post else None

            post_data = {
                "id": post_id,
                "thread_id": first_post["no"],
                "timestamp": post["time"],
                "subject": post["sub"] if "sub" in post else "",
                "body": post["com"] if "com" in post else "",
                "author": post["name"] if "name" in post else "",
                "author_trip": post["trip"] if "trip" in post else "",
                "author_type": post["id"] if "id" in post else "",
                "author_type_id": post["capcode"] if "capcode" in post else "",
                "country_code": post["country"] if "country" in post else "",
                "country_name": post["country_name"] if "country_name" in post else "",
                "image_file": post["filename"] + post["ext"] if "filename" in post else "",
                "image_4chan": str(post["tim"]) + post["ext"] if "filename" in post else "",
                "image_md5": post["md5"] if "md5" in post else "",
                "image_filesize": post["fsize"] if "fsize" in post else 0,
                "image_dimensions": json.dumps(dimensions),
                "semantic_url": post["semantic_url"] if "semantic_url" in post else "",
                "unsorted_data": json.dumps(
                    {field: post[field] for field in post.keys() if field not in self.known_fields})
            }

            self.db.insert("posts", post_data, commit=False)
            self.db.execute("UPDATE posts SET body_vector = to_tsvector(body) WHERE id = %s", (post_id, ))

            self.save_links(post, post_id)
            if "filename" in post:
                self.queue_image(post, thread)

            new_posts += 1

        # save to database
        self.log.info("Updating thread %s/%s, new posts: %s, deleted: %s" % (
            self.job["details"]["board"], first_post["no"], new_posts, len(deleted)))
        self.db.commit()

    def save_links(self, post, post_id):
        """
        Save links to other posts in the given post

        Links are wrapped in a link with the "quotelink" class; the link is
        saved as a simple Post ID => Linked ID mapping.

        :param dict post:  Post data
        :param int post_id:  ID of the given post
        """
        if "com" in post:
            links = re.findall('<a href="#p([0-9]+)" class="quotelink">', post["com"])
            for linked_post in links:
                if len(str(linked_post)) < 15:
                    self.db.insert("posts_mention", {"post_id": post_id, "mentioned_id": linked_post}, commit=False)

    def queue_image(self, post, thread):
        """
        Queue image for downloading

        This queues the image for downloading, if it hasn't been downloaded yet
        and a valid image folder has been set. This is the only place in the
        backend where the image path is determined!

        :param dict post:  Post data to queue image download for
        :param dict thread:  Thread data of thread within which image was posted
        """
        md5 = hashlib.md5()
        md5.update(base64.b64decode(post["md5"]))
        image_path = config.PATH_IMAGES + "/" + md5.hexdigest() + post["ext"]

        if os.path.isdir(config.PATH_IMAGES) and not os.path.isfile(image_path):
            try:
                self.queue.add_job("image", remote_id=post["md5"], details={
                    "board": thread["board"],
                    "ext": post["ext"],
                    "tim": post["tim"],
                    "destination": image_path
                })
            except JobAlreadyExistsException:
                pass

    def update_thread(self, first_post, last_reply, last_post):
        """
        Update thread info

        Processes post data for the OP to see if the thread for that OP needs
        updating.

        :param dict first_post:  Post data for the OP
        :param int last_reply:  Timestamp of last reply in thread
        :param int last_post:  ID of last post in thread
        :return: Thread data (dict), updated, or `None` if no further work is needed
        """
        # we need the following to check whether the thread has changed since the last scrape
        num_replies = first_post["replies"] + 1

        thread = self.db.fetchone("SELECT * FROM threads WHERE id = %s", (first_post["no"],))
        if not thread:
            self.log.warning("Tried to scrape post before thread %s was scraped" % first_post["no"])
            return None

        if thread["num_replies"] == num_replies and thread["timestamp_modified"] == last_reply:
            # no updates, no need to check posts any further
            self.log.debug("No new messages in thread %s" % first_post["no"])
            return None

        # first post has useful metadata for the *thread*
        thread_update = {
            "num_unique_ips": first_post["unique_ips"] if "unique_ips" in first_post else -1,
            "num_images": first_post["images"],
            "num_replies": num_replies,
            "limit_bump": True if "bumplimit" in first_post and first_post["bumplimit"] == 1 else False,
            "limit_image": True if "imagelimit" in first_post and first_post["imagelimit"] == 1 else False,
            "is_sticky": True if "sticky" in first_post and first_post["sticky"] == 1 else False,
            "is_closed": True if "closed" in first_post and first_post["closed"] == 1 else False,
            "post_last": last_post
        }

        if "archived" in first_post and first_post["archived"] == 1:
            thread_update["timestamp_archived"] = first_post["archived_on"]

        self.db.update("threads", where={"id": first_post["no"]}, data=thread_update)
        return {**thread, **thread_update}

    def get_url(self):
        """
        Get URL to scrape for the current job

        :return string: URL to scrape
        """
        return "http://a.4cdn.org/%s/thread/%s.json" % (self.job["details"]["board"], self.job["remote_id"])
