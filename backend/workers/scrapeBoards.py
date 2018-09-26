import time

from lib.scraper import BasicJSONScraper
from lib.database import Database


class BoardScraper(BasicJSONScraper):
    """
    Scrape 4chan boards

    The threads found aren't saved themselves, but new jobs are created to scrape the
    individual threads so post data can be saved
    """
    type = "board"
    pause = 1  # we're not checking this often, but using claim-after to schedule jobs
    max_workers = 2  # should be equivalent to the amount of boards to scrape

    def __init__(self):
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
                    "positions": ""
                }

                # schedule a job for scraping the thread's posts
                self.queue.addJob(type="thread", remote_id=thread["no"], details={"board": self.jobdata["remote_id"]})

                # add database record for thread, if none exists yet
                thread = self.db.fetchone("SELECT * FROM threads WHERE id = %s", (thread_data["id"],))
                if not thread:
                    self.db.insert("thread", thread_data)

                # update timestamps and position
                position_update = self.loop_time + ":" + position + ",", thread_data["id"]
                self.db.execute("UPDATE threads SET timestamp_scraped = %s, timestamp_modified = %s,"
                                "index_positions = index_positions + %s WHERE id = %s",
                                (self.loop_time, thread["modified"], position_update))

    def after_process(self):
        """
        After the job is finished, schedule another scrape a minute later
        """
        # scrape again a minute later
        self.queue.finishJob(self.jobdata["id"])
        self.queue.addJob("board", remote_id=self.jobdata["remote_id"], details=self.jobdata["details"], claim_after=time.time() + 60)

    def get_url(self, data):
        """
        Get URL to scrape for the current job

        :param dict data:  Job data - contains the ID of the board to scrape
        :return string: URL to scrape
        """
        return "https://a.4cdn.org/%s/threads.json" % data["remote_id"]
