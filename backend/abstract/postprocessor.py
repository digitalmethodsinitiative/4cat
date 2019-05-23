"""
Basic post-processor worker - should be inherited by workers to post-process results
"""
import shutil
import abc
import os

from backend.abstract.worker import BasicWorker
from backend.lib.query import DataSet
from backend.lib.helpers import get_software_version, load_postprocessors


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
		self.query = DataSet(key=self.job.data["remote_id"], db=self.db)
		self.parent = DataSet(key=self.query.data["key_parent"], db=self.db)
		if not self.parent.is_finished():
			# not finished yet - retry after a while
			self.job.release(delay=30)
			return

		self.log.info("Running post-processor %s on query %s" % (self.type, self.job.data["remote_id"]))

		self.parameters = self.query.parameters
		self.query.update_status("Processing data")
		self.query.update_version(get_software_version())

		self.parent = DataSet(key=self.query.data["key_parent"], db=self.db)
		self.source_file = self.parent.get_results_path()

		if not os.path.exists(self.source_file):
			self.query.update_status("Finished, no input data found.")
		elif not self.query.is_finished():
			self.process()

		self.after_process()

	def after_process(self):
		"""
		After processing, declare job finished
		"""
		self.query.update_status("Results processed")
		if not self.query.is_finished():
			self.query.finish()

		# see if we have anything else lined up to run next
		for next in self.parameters.get("next", []):
			next_parameters = next.get("parameters", {})
			next_type = next.get("type", "")
			available_postprocessors = self.query.get_available_postprocessors()

			# run it only if the post-processor is actually available for this query
			if next_type in available_postprocessors:
				next_analysis = DataSet(parameters=next_parameters, type=next_type, db=self.db, parent=self.query.key, extension=available_postprocessors[next_type]["extension"])
				self.queue.add_job(next_type, remote_id=next_analysis.key)

		# see if we need to register the result somewhere
		if "copy_to" in self.parameters:
			# copy the results to an arbitray place that was passed
			if os.path.exists(self.query.get_results_path()):
				# but only if we actually have something to copy
				shutil.copyfile(self.query.get_results_path(), self.parameters["copy_to"])
			else:
				# if copy_to was passed, that means it's important that this
				# file exists somewhere, so we create it as an empty file
				with open(self.parameters["copy_to"], "w") as empty_file:
					empty_file.write("")

		self.job.finish()

	@abc.abstractmethod
	def process(self):
		"""
		Process scraped data

		:param data:  Parsed JSON data
		"""
		pass