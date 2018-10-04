import os.path
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

        :param dict data: The thread data, parsed JSON data
        """
        # add post data to database
        if "posts" not in data or len(data["posts"]) == 0:
            self.log.warning(
                "JSON response for thread %s contained no posts, could not process" % self.job["remote_id"])
            return

        # check if OP has all the required data
        op = data["posts"][0]
        missing = set(self.required_fields_op) - set(op.keys())
        if missing != set():
            self.log.warning("OP is missing required fields %s, ignoring" % repr(missing))
            return

        # we need the following to check whether the thread has changed since the last scrape
        num_replies = op["replies"] + 1
        last_reply = max([post["time"] for post in data["posts"]])
        last_post = max([post["no"] for post in data["posts"]])

        thread = self.db.fetchone("SELECT * FROM threads WHERE id = %s", (op["no"],))
        if not thread:
            self.log.warning("Tried to scrape post before thread %s was scraped" % op["no"])
            return

        if thread["num_replies"] == num_replies and thread["timestamp_modified"] == last_reply:
            # no updates, no need to check posts any further
            self.log.debug("No new messages in thread %s" % op["no"])
            return

        # first post has useful metadata for the *thread*
        thread_update = {
            "num_unique_ips": op["unique_ips"] if "unique_ips" in op else -1,
            "num_images": op["images"],
            "num_replies": num_replies,
            "limit_bump": True if "bumplimit" in op and op["bumplimit"] == 1 else False,
            "limit_image": True if "imagelimit" in op and op["imagelimit"] == 1 else False,
            "is_sticky": True if "sticky" in op and op["sticky"] == 1 else False,
            "is_closed": True if "closed" in op and op["closed"] == 1 else False,
            "post_last": last_post
        }

        if "archived" in op and op["archived"] == 1:
            thread_update["is_archived"] = True
            thread_update["timestamp_archived"] = op["archived_on"]

        self.db.update("threads", where={"id": op["no"]}, data=thread_update)

        # create a dict mapped as `post id`: `post data` for easier comparisons with existing data
        post_dict_scrape = {post["no"]: post for post in data["posts"]}
        post_dict_db = {post["id"]: post for post in
                        self.db.fetchall("SELECT * FROM posts WHERE thread_id = %s", (op["no"],))}

        # mark deleted posts as such
        deleted = set(post_dict_db.keys()) - set(post_dict_scrape.keys())
        for post_id in deleted:
            self.db.update("posts", where={"id": post_id}, data={"is_deleted": True}, commit=False)
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
                "thread_id": op["no"],
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
                "is_deleted": False,
                "unsorted_data": json.dumps(
                    {field: post[field] for field in post.keys() if field not in self.known_fields})
            }

            self.db.insert("posts", post_data, commit=False)
            new_posts += 1

            # find links to other posts in post body and save those links to the database
            if "com" in post:
                links = re.findall('<a href="#p([0-9]+)" class="quotelink">', post["com"])
                for linked_post in links:
                    self.db.insert("posts_mention", {"post_id": post_id, "mentioned_id": linked_post}, commit=False)

            # check if there is in image with the post, and schedule downloading if it has not been downloaded yet
            if "filename" not in post:
                continue

            image_path = config.image_path + "/" + post["md5"] + post["ext"]
            if not os.path.isfile(image_path):
                try:
                    self.queue.addJob("image", remote_id=post["md5"], details={
                        "board": thread["board"],
                        "ext": post["ext"],
                        "md5": post["md5"],
                        "tim": post["tim"]
                    })
                except JobAlreadyExistsException:
                    pass

        # save to database
        self.log.info("Updating thread %s, new posts: %s, deleted: %s" % (op["no"], new_posts, len(deleted)))
        self.db.commit()

    def get_url(self):
        """
        Get URL to scrape for the current job

        :return string: URL to scrape
        """
        return "http://a.4cdn.org/%s/thread/%s.json" % (self.job["details"]["board"], self.job["remote_id"])
