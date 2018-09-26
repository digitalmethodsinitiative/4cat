import os.path
import json

from lib.scraper import BasicJSONScraper
from lib.database import Database

from config import config


class ThreadScraper(BasicJSONScraper):
    """
    Scrape 4chan threads

    This scrapes individual threads, and saves the posts into the database.
    """
    type = "thread"
    max_workers = 2
    pause = 1  # we're not checking this often, but using claim-after to schedule scrapes

    # for new posts, any fields not in here will be saved in the "unsorted_data" column
    # for that post as part of a JSONified dict
    known_fields = ["no", "com", "name", "filename", "md5", "fsize", "semantic_url",
                    "resto", "time", "w", "h", "tn_w", "tn_h", "tim"]

    def __init__(self):
        super().__init__()

        self.db = Database()

    def process(self, data):
        """
        Process scraped thread data

        :param dict data: The thread data, parsed JSON data
        """
        db = Database()

        # add post data to database
        if "posts" not in data or len(data["posts"]) == 0:
            self.log.warning("JSON response for thread %s contained no posts, could not process" % self.jobdata["remote_id"])
            return

        # we need the following to check whether the thread has changed since the last scrape
        op = data["posts"][0]
        num_replies = op["replies"] + 1
        last_reply = max([post["time"] for post in data["posts"]])
        last_post = max([post["no"] for post in data["posts"]])

        thread = self.db.fetchone("SELECT * FROM threads WHERE id = %s", op["no"])
        if thread["num_replies"] == num_replies and thread["timestamp_modified"] == last_reply:
            # no updates, no need to check posts any further
            return

        # first post has useful metadata for the *thread*
        thread_update = {
            "num_unique_ips": op["unique_ips"],
            "num_images": op["image"],
            "num_replies": num_replies,
            "limit_bump": op["bumplimit"],
            "limit_image": op["imagelimit"],
            "is_sticky": 1 if "sticky" in op and op["sticky"] == 1 else 0,
            "is_closed": 1 if "closed" in op and op["closed"] == 1 else 0,
            "last_post": last_post
        }

        self.db.update("threads", where={"id": op["no"]}, data=thread_update)

        post_dict_scrape = {post["no"]: post for post in data["posts"]}
        post_dict_db = {post["id"]: post for post in self.db.fetchall("SELECT * FROM posts WHERE thread = %s", (op["no"],))}

        # mark deleted posts as such
        deleted = set(post_dict_db.keys()) - set(post_dict_scrape.keys())
        for post_id in deleted:
            self.db.update("posts", where={"id": post_id}, data={"is_deleted": True}, commit=False)
        self.db.commit()

        # add new posts
        new = set(post_dict_scrape.keys()) - set(post_dict_db.keys())
        for post_id in new:
            post = post_dict_scrape[post_id]
            post_data = {
                "id": post_id,
                "thread_id": op["no"],
                "timestamp": post["time"],
                "body": post["com"],
                "author": post["name"],
                "image_file": post["filename"] + post["ext"] if "filename" in post and "ext" in post else "",
                "image_4chan": post["tim"] + post["ext"] if "filename" in post and "ext" in post else "",
                "image_md5": post["md5"] if "md5" in post else "",
                "image_filesize": post["fsize"] if "fsize" in post else "",
                "semantic_url": post["semantic_url"] if "semantic_url" in post else "",
                "is_deleted": False,
                "unsorted_data": json.dumps({field: post[field] for field in post.keys() if field not in self.known_fields})
            }
            self.db.insert("posts", post_data, commit=False)

            # check if there is in image with the post, and schedule downloading if it has not
            # been downloaded yet
            if "md5" not in post:
                continue

            image_path = config.image_path + "/" + post_data["md5"] + post_data["ext"]
            if post_data["image_4chan"] != "" and not os.path.isfile(image_path):
                self.queue.addJob("image", details={
                    "board": thread["board"],
                    "ext": post["ext"],
                    "md5": post["md5"],
                    "tim": post["tim"]
                })
        self.db.commit()

    def get_url(self, data):
        """
        Get URL to scrape for the current job

        :param dict data:  Job data - contains the ID of the thread to scrape
        :return string: URL to scrape
        """
        return "https://a.4cdn.org/%s/thread/%s.json" % (self.jobdata["details"]["board"], self.jobdata["remote_id"])
