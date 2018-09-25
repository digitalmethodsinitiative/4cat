from lib.scraper import BasicJSONScraper
from lib.queue import JobQueue, JobAlreadyExistsException


class BoardScraper(BasicJSONScraper):
    """
    Scrape 4chan boards

    The threads found aren't saved themselves, but new jobs are created to scrape the
    individual threads so post data can be saved
    """
    type = "board"
    pause = 60

    def process(self, data):
        """
        Process scraped board data

        Creates new jobs based on thread IDs found

        :param dict data: The board data, parsed JSON data
        """
        queue = JobQueue()

        for page in data:
            for thread in page["threads"]:
                try:
                    queue.addJob(type="thread", details=[], remote_id=thread["no"])
                except JobAlreadyExistsException:
                    pass

    def getUrl(self, data):
        """
        Get URL to scrape for the current job

        :param dict data:  Job data - contains the ID of the thread to scrape
        :return string: URL to scrape
        """
        return "https://a.4cdn.org/tg/threads.json"
