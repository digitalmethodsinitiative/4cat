"""
Basic post-processor worker - should be inherited by workers to post-process results
"""
import abc

from backend.abstract.worker import BasicWorker
from backend.lib.query import DataSet
from backend.lib.helpers import get_software_version


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
	category = "Other"
	extension = "csv"
	options = {}
	parameters = {}

	def __init__(self, db=None, logger=None, manager=None, job=job):
		"""
		Set up database connection - we need one to store the thread data
		"""
		super().__init__(db=db, logger=logger, manager=manager, job=job)

	def work(self):
		"""
		Scrape a URL

		This acquires a job - if none are found, the loop pauses for a while. The job's URL
		is then requested and parsed. If that went well, the parsed data is passed on to the
		processor.
		"""
		self.log.info("Running post-processor %s on query %s" % (self.type, self.job.data["remote_id"]))

		self.query = DataSet(key=self.job.data["remote_id"], db=self.db)
		self.parameters = self.query.parameters
		self.query.update_status("Processing data")
		self.query.update_version(get_software_version())

		self.parent = DataSet(key=self.query.data["key_parent"], db=self.db)
		self.source_file = self.parent.get_results_path()

		if not self.query.is_finished():
			self.process()

		self.after_process()

	def after_process(self):
		"""
		After processing, declare job finished
		"""
		self.query.update_status("Results processed")
		if not self.query.is_finished():
			self.query.finish()
		self.job.finish()

	@abc.abstractmethod
	def process(self):
		"""
		Process scraped data

		:param data:  Parsed JSON data
		"""
		pass