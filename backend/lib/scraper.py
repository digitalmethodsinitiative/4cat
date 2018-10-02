import requests
import random
import time
import json
import abc

from lib.worker import BasicWorker
from lib.queue import JobClaimedException
from lib.database import Database


class BasicJSONScraper(BasicWorker, metaclass=abc.ABCMeta):
    """
    Abstract JSON scraper class

    The job queue is continually checked for jobs of this scraper's type. If any are found,
    the URL for that job is scraped and the result is parsed as JSON. The parsed JSON is
    then passed to a processor method for further handling.
    """
    db = None

    def __init__(self, logger):
        """
        Set up database connection - we need one to store the thread data
        """
        super().__init__(logger)

        self.db = Database(logger=self.log)

    def work(self):
        """
        Scrape a URL

        This acquires a job - if none are found, the loop pauses for a while. The job's URL
        is then requested and parsed. If that went well, the parsed data is passed on to the
        processor.
        """
        job = self.queue.getJob(self.type)
        if not job:
            self.log.info("Scraper (%s) has no jobs, sleeping for 10 seconds" % self.type)
            time.sleep(10)
            return

        # claim the job - this is needed so multiple workers don't do the same job
        self.jobdata = job

        try:
            self.queue.claimJob(job["id"])
        except JobClaimedException:
            # too bad, so sad
            return

        # request URL
        url = self.get_url(self.jobdata)
        try:
            data = requests.get(url, timeout=5)
        except (requests.HTTPError, requests.exceptions.ReadTimeout):
            self.queue.releaseJob(job["id"], delay=10)  # try again in 10 seconds
            self.log.warning("Could not finish request for %s, releasing job" % url)
            return

        # parse as JSON
        try:
            jsondata = json.loads(data.content)
        except json.JSONDecodeError:
            print(repr(data))
            self.log.warning(
                "Could not decode JSON response for %s scrape (remote ID %s, job ID %s) - retrying later" % (
                    self.type, job["remote_id"], job["id"]))
            self.queue.releaseJob(job["id"], delay=random.choice(range(5,35)))  # try again later
            return

        # finally, pass it on
        self.process(jsondata)
        self.after_process()

    def after_process(self):
        """
        After processing, declare job finished
        """
        self.queue.finishJob(self.jobdata["id"])

    @abc.abstractmethod
    def process(self, data):
        """
        Process scraped data

        :param data:  Parsed JSON data
        """
        pass

    @abc.abstractmethod
    def get_url(self, data):
        """
        Get URL to scrape

        :param data:  Job data
        :return:
        """
        pass
