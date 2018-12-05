"""
Basic post-processor worker - should be inherited by workers to post-process results
"""
import time
import abc

from backend.lib.worker import BasicWorker
from backend.lib.queue import JobClaimedException
from backend.lib.query import SearchQuery


class BasicPostProcessor(BasicWorker, metaclass=abc.ABCMeta):
	"""
	Abstract post-processor class

	A post-processor takes a finished search query as input and processed its
	result in some way, with another result set as output. The input thus is
	a CSV file, and the output (usually) as well. In other words, the result of
	a post-processor run can be used as input for another post-processor
	(though whether this is useful is another question).
	"""
	db = None
	query = None
	job = None
	parent = None
	source_file = None
	description = "No description available"
	extension = "csv"

	def __init__(self, db=None, logger=None, manager=None):
		"""
		Set up database connection - we need one to store the thread data
		"""
		super().__init__(db=db, logger=logger, manager=manager)
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
			self.log.debug("Post-processor (%s) has no jobs, sleeping for 10 seconds" % self.type)
			time.sleep(10)
			return

		# claim the job - this is needed so multiple workers don't do the same job
		self.job = job

		try:
			self.queue.claim_job(job)
		except JobClaimedException:
			# too bad, so sad
			return

		self.log.info("Running post-processor %s on query %s" % (self.type, job["remote_id"]))
		self.parent = SearchQuery(key=job["remote_id"], db=self.db)
		self.source_file = self.parent.get_results_path()

		# create new query, for the result of this process
		params = {
			"type": self.type
		}

		if self.job["details"]:
			for field in self.job["details"]:
				params[field] = self.job["details"][field]

		self.query = SearchQuery(query=self.parent.query, parent=self.parent.key, parameters=params, db=self.db, extension=self.extension)
		self.process()
		self.after_process()

	def after_process(self):
		"""
		After processing, declare job finished
		"""
		self.query.update_status("Results processed.")
		if not self.query.is_finished():
			self.query.finish()
		self.queue.finish_job(self.job)

	@abc.abstractmethod
	def process(self):
		"""
		Process scraped data

		:param data:  Parsed JSON data
		"""
		pass