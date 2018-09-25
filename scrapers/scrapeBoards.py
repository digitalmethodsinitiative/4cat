from lib.scraper import BasicJSONScraper
from lib.queue import JobQueue, JobAlreadyExistsException


class BoardScraper(BasicJSONScraper):
    type = "board"
    pause = 60

    def process(self, data):
        # queue board's threads for scraping
        queue = JobQueue()

        for page in data:
            for thread in page["threads"]:
                try:
                    queue.addJob(type="thread", details=[], remote_id=thread["no"])
                except JobAlreadyExistsException:
                    pass

    def getUrl(self, data):
        return "https://a.4cdn.org/tg/threads.json"
