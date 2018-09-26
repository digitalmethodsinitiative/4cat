import psycopg2

from lib.scraper import BasicJSONScraper
from lib.database import Database


class ThreadScraper(BasicJSONScraper):
    """
    Scrape 4chan threads

    This scrapes individual threads, and saves the posts into the database.
    """
    type = "thread"
    max_workers = 5

    def process(self, data):
        """
        Process scraped thread data

        :param dict data: The thread data, parsed JSON data
        """
        db = Database()

        # add post data to database
        for post in data["posts"]:
            if "com" not in post:
                post["com"] = ""

            try:
                db.update("INSERT INTO posts (id, post) VALUES (%s, %s)", (post["no"], post["com"]))
            except psycopg2.IntegrityError:
                db.commit()

    def getUrl(self, data):
        """
        Get URL to scrape for the current job

        :param dict data:  Job data - contains the ID of the thread to scrape
        :return string: URL to scrape
        """
        return "https://a.4cdn.org/tg/thread/%s.json" % self.jobdata["remote_id"]
