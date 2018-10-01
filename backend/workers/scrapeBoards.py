import time

from lib.scraper import BasicJSONScraper
from lib.database import Database
from lib.queue import JobAlreadyExistsException


class BoardScraper(BasicJSONScraper):
    """
    Scrape 4chan boards

    The threads found aren't saved themselves, but new jobs are created to scrape the
    individual threads so post data can be saved
    """
    type = "board"
    pause = 1  # we're not checking this often, but using claim-after to schedule jobs
    max_workers = 2  # should probably be equivalent to the amount of boards to scrape

    def __init__(self):
        """
        Set up database connection - we need one to store the thread data
        """
        super().__init__()

        self.db = Database()

    def process(self, data):
        """
        Process scraped board data

        For each thread, a record is inserted into the database if it does not exist yet

        :param dict data: The board data, parsed JSON data
        """
        position = 1
        for page in data:
            for thread in page["threads"]:
                position += 1

                thread_data = {
                    "id": thread["no"],
                    "board": self.jobdata["remote_id"],
                    "index_positions": ""
                }

                # schedule a job for scraping the thread's posts
                try:
                    self.queue.addJob(type="thread", remote_id=thread["no"], details={"board": self.jobdata["remote_id"]})
                except JobAlreadyExistsException:
                    pass

                # add database record for thread, if none exists yet
                thread_row = self.db.fetchone("SELECT * FROM threads WHERE id = %s", (thread_data["id"],))
                if not thread_row:
                    self.db.insert("threads", thread_data)

                # update timestamps and position
                position_update = str(self.loop_time) + ":" + str(position) + ",", thread_data["id"]
                self.db.execute("UPDATE threads SET timestamp_scraped = %s, timestamp_modified = %s,"
                                "index_positions = CONCAT(index_positions, %s) WHERE id = %s",
                                (self.loop_time, thread["last_modified"], position_update, thread_data["id"]))

    def get_url(self, data):
        """
        Get URL to scrape for the current job

        :param dict data:  Job data - contains the ID of the board to scrape
        :return string: URL to scrape
        """
        return "http://a.4cdn.org/%s/threads.json" % data["remote_id"]
