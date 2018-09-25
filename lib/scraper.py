import threading
import requests
import time
import json

from lib.queue import JobQueue, JobClaimedException
from lib.logger import Logger


class BasicJSONScraper:
    """
    Abstract JSON scraper class

    This starts a separate thread in which the job queue is continually checked for
    jobs of this scraper's type. If any are found, the URL for that job is scraped
    and the result is parsed as JSON. The parsed JSON is then passed to a processor
    function for further handling.
    """
    type = "misc"  # this should match the job type as saved in the database
    jobdata = {}

    queue = None
    log = None
    looping = True
    thread = None

    def __init__(self):
        """
        Set up queue and log handlers, and start a thread
        """
        super().__init__()
        self.queue = JobQueue()
        self.log = Logger()

        self.thread = threading.Thread(target=self.loop, name=self.type)
        self.thread.start()

    def isAlive(self):
        """
        Check if scraper thread is still alive

        If not, it has ended - this *should* happen only when `abort()` is called.
        :return bool:
        """
        return self.thread.isAlive()

    def abort(self):
        """
        Stop the scraping loop, and end the thread.
        """
        self.looping = False
        self.thread.join()

    def loop(self):
        """
        Loop the scraper

        This simply scrapes continually, with a pause in-between scrapes.
        """
        while self.looping:
            self.scrape()
            time.sleep(1)

    def scrape(self):
        """
        Scrape an URL

        This acquires a job - if none are found, the loop pauses for a while. The job's URL
        is then requested and parsed. If that went well, the parsed data is passed on to the
        processor.
        """
        job = self.queue.getJob(self.type)
        if not job:
            time.sleep(10)
            self.log.info("Scraper (%s) has no jobs, sleeping for 10 seconds" % self.type)
            return

        # claim the job - this is needed so multiple scrapers don't do the same job
        self.jobdata = job
        self.queue.claimJob(job["id"])

        # request URL
        url = self.getUrl(self.jobdata)
        try:
            data = requests.get(url, timeout=5)
        except requests.HTTPError:
            self.queue.releaseJob(job["id"])  # try again later
            self.log.warning("Could not finish request for %s, releasing job" % url)
            return

        # parse as JSON
        try:
            jsondata = json.loads(data.content)
        except json.JSONDecodeError:
            print(repr(data.content))
            self.log.warning(
                "Could not decode JSON response for %s scrape (remote ID %s, job ID %s) - releasing job" % (
                    self.type, job["remote_id"], job["id"]))
            self.queue.releaseJob(job["id"])  # try again later
            return

        # finally, pass it on
        self.process(jsondata)

    def process(self, data):
        raise NotImplementedError("A child class needs to implement this method.")

    def getUrl(self, data):
        raise NotImplementedError("A child class needs to implement this method.")
