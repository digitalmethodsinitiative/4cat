"""
Basic scraper worker - should be inherited by workers to scrape specific types of content
"""
import requests
import random
import time
import json
import abc

from backend.lib.worker import BasicWorker
from backend.lib.queue import JobClaimedException

import config

class BasicJSONScraper(BasicWorker, metaclass=abc.ABCMeta):
	"""
	Abstract JSON scraper class

	The job queue is continually checked for jobs of this scraper's type. If any are found,
	the URL for that job is scraped and the result is parsed as JSON. The parsed JSON is
	then passed to a processor method for further handling.
	"""
	db = None

	def __init__(self, db=None, logger=None):
		"""
		Set up database connection - we need one to store the thread data
		"""
		super().__init__(db=db, logger=logger)
		self.job = {}

	def work(self):
		"""
		Scrape a URL

		This acquires a job - if none are found, the loop pauses for a while. The job's URL
		is then requested and parsed. If that went well, the parsed data is passed on to the
		processor.
		"""
		job = self.queue.get_job(self.type)
		if not job:
			self.log.debug("Scraper (%s) has no jobs, sleeping for 10 seconds" % self.type)
			time.sleep(10)
			return

		# claim the job - this is needed so multiple workers don't do the same job
		self.job = job

		try:
			self.queue.claim_job(job)
		except JobClaimedException:
			# too bad, so sad
			return

		# request URL
		url = self.get_url()
		try:
			# see if any proxies were configured that would work for this URL
			protocol = url.split(":")[0]
			if protocol in config.SCRAPE_PROXIES and config.SCRAPE_PROXIES[protocol]:
				proxies = {protocol: random.choice(config.SCRAPE_PROXIES[protocol])}
			else:
				proxies = None

			# do the request!
			data = requests.get(url, timeout=config.SCRAPE_TIMEOUT, proxies=proxies)
		except (requests.HTTPError, requests.exceptions.ReadTimeout, ConnectionError):
			self.queue.release_job(job, delay=10)  # try again in 10 seconds
			self.log.warning("Could not finish request for %s, releasing job" % url)
			return

		# parse as JSON
		try:
			jsondata = json.loads(data.content)
		except json.JSONDecodeError as e:
			if job["details"] and "board" in job["details"]:
				id = job["details"]["board"] + "/" + job["remote_id"]
			else:
				id = job["remote_id"]

			if self.job["attempts"] > 2:
				# todo: determine if this means the thread was deleted
				self.log.warning(
					"JSON for %s %s unparseable after %i attempts, aborting" % (
						self.type, id, job["attempts"]))
				self.queue.finish_job(job)
			else:
				self.log.info(
					"JSON for %s %s unparseable, retrying later (%s)" % (
						self.type, id, e))
				self.queue.release_job(job, delay=random.choice(range(5, 35)))  # try again later

			return

		# finally, pass it on
		self.process(jsondata, job)
		self.after_process()

	def after_process(self):
		"""
		After processing, declare job finished
		"""
		self.queue.finish_job(self.job)

	@abc.abstractmethod
	def process(self, data, job):
		"""
		Process scraped data

		:param data:  Parsed JSON data
		"""
		pass

	@abc.abstractmethod
	def get_url(self):
		"""
		Get URL to scrape

		:return string:  URL to scrape
		"""
		pass
