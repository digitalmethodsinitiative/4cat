"""
Basic scraper worker - should be inherited by workers to scrape specific types of content
"""
import requests
import random
import json
import abc

from backend.abstract.worker import BasicWorker

import config


class BasicHTTPScraper(BasicWorker, metaclass=abc.ABCMeta):
	"""
	Abstract JSON scraper class

	The job queue is continually checked for jobs of this scraper's type. If any are found,
	the URL for that job is scraped and the result is parsed as JSON. The parsed JSON is
	then passed to a processor method for further handling.
	"""
	db = None

	def __init__(self, job, db=None, logger=None, manager=None):
		"""
		Set up database connection - we need one to store the thread data
		"""
		super().__init__(db=db, logger=logger, manager=manager, job=job)
		self.prefix = self.type.split("-")[0]

	def work(self):
		"""
		Scrape a URL

		This acquires a job - if none are found, the loop pauses for a while. The job's URL
		is then requested and parsed. If that went well, the parsed data is passed on to the
		processor.
		"""

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
		except (requests.exceptions.RequestException, ConnectionRefusedError) as e:
			if self.job.data["attempts"] > 2:
				self.job.finish()
				self.log.error("Could not finish request for %s (%s), cancelling job" % (url, e))
			else:
				self.job.release(delay=10)
				self.log.info("Could not finish request for %s (%s), releasing job" % (url, e))
			return

		if "board" in self.job.details:
			id = self.job.details["board"] + "/" + self.job.data["remote_id"]
		else:
			id = self.job.data["remote_id"]

		if data.status_code == 404:
			# this should be handled differently from an actually erroneous response
			# because it may indicate that the resource has been deleted
			self.not_found()
		else:
			data = self.parse(data.content)
			if data is None:
				if self.job.data["attempts"] > 2:
					self.log.info("Data for %s %s could not be parsed, retrying later" % (self.type, id))
					self.job.release(delay=random.choice(range(15, 45)))  # try again later
				else:
					self.log.warning("Data for %s %s could not be parsed after %i attempts, aborting" % (
					self.type, id, self.job.data["attempts"]))
					self.job.finish()
				return

			# finally, pass it on
			self.process(data)
			self.after_process()

	def after_process(self):
		"""
		After processing, declare job finished
		"""
		self.job.finish()

	def not_found(self):
		"""
		Called if the job could not be completed because the request returned
		a 404 response. This does not necessarily indicate failure.
		"""
		self.job.finish()

	def parse(self, data):
		"""
		Parse incoming data

		Can be overridden to, e.g., parse JSON data

		:param data:  Body of HTTP request
		:return:  Parsed data
		"""
		return data

	@abc.abstractmethod
	def process(self, data):
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


class BasicJSONScraper(BasicHTTPScraper, metaclass=abc.ABCMeta):
	"""
	Scraper for JSON-based data
	"""

	def parse(self, data):
		"""
		Parse data as JSON

		:param str data:  Incoming JSON-encoded data
		:return:  Decoded JSON object
		"""
		try:
			return json.loads(data)
		except json.JSONDecodeError:
			return None
