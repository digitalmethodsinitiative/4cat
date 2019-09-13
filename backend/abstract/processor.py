"""
Basic post-processor worker - should be inherited by workers to post-process results
"""
import shutil
import abc

from backend.abstract.worker import BasicWorker
from backend.lib.dataset import DataSet
from backend.lib.helpers import get_software_version


class BasicProcessor(BasicWorker, metaclass=abc.ABCMeta):
	"""
	Abstract post-processor class

	A post-processor takes a finished search query as input and processed its
	result in some way, with another result set as output. The input thus is
	a CSV file, and the output (usually) as well. In other words, the result of
	a post-processor run can be used as input for another post-processor
	(though whether this is useful is another question).
	"""
	db = None
	dataset = None
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
		try:
			self.dataset = DataSet(key=self.job.data["remote_id"], db=self.db)
		except TypeError:
			# query has been deleted in the meantime. finish without error,
			# as deleting it will have been a conscious choice by a user
			self.job.finish()
			return

		if self.dataset.type != "search":
			try:
				self.parent = DataSet(key=self.dataset.data["key_parent"], db=self.db)
			except TypeError:
				# we need to know what the parent dataset was to properly handle the
				# analysis
				self.log.warning("Processor %s queued for orphan query %s: cannot run, cancelling job" % (
					self.type, self.dataset.key))
				self.job.finish()
				return

			if not self.parent.is_finished():
				# not finished yet - retry after a while
				self.job.release(delay=30)
				return

			self.parent = DataSet(key=self.dataset.data["key_parent"], db=self.db)

			self.source_file = self.parent.get_results_path()
			if not self.source_file.exists():
				self.dataset.update_status("Finished, no input data found.")

		self.log.info("Running post-processor %s on query %s" % (self.type, self.job.data["remote_id"]))

		self.parameters = self.dataset.parameters
		self.dataset.update_status("Processing data")
		self.dataset.update_version(get_software_version())

		if not self.dataset.is_finished():
			self.process()

		self.after_process()

	def after_process(self):
		"""
		After processing, declare job finished
		"""
		self.dataset.update_status("Results processed")
		if not self.dataset.is_finished():
			self.dataset.finish()

		# see if we have anything else lined up to run next
		for next in self.parameters.get("next", []):
			next_parameters = next.get("parameters", {})
			next_type = next.get("type", "")
			available_processors = self.dataset.get_available_processors()

			# run it only if the post-processor is actually available for this query
			if next_type in available_processors:
				next_analysis = DataSet(parameters=next_parameters, type=next_type, db=self.db, parent=self.dataset.key,
										extension=available_processors[next_type]["extension"])
				self.queue.add_job(next_type, remote_id=next_analysis.key)

		# see if we need to register the result somewhere
		if "copy_to" in self.parameters:
			# copy the results to an arbitray place that was passed
			if self.dataset.get_results_path().exists():
				shutil.copyfile(str(self.dataset.get_results_path()), self.parameters["copy_to"])
			else:
				# if copy_to was passed, that means it's important that this
				# file exists somewhere, so we create it as an empty file
				with open(self.parameters["copy_to"], "w") as empty_file:
					empty_file.write("")

		# see if this query chain is to be attached to another query
		# if so, the full genealogy of this query (minus the original dataset)
		# is attached to the given query - this is mostly useful for presets,
		# where a chain of processors can be marked as 'underlying' a preset
		if "attach_to" in self.parameters:
			try:
				# copy metadata and results to the surrogate
				surrogate = DataSet(key=self.parameters["attach_to"], db=self.db)

				if self.dataset.get_results_path().exists():
					shutil.copyfile(str(self.dataset.get_results_path()), str(surrogate.get_results_path()))

				top_parent = self.dataset.get_genealogy()[1]
				top_parent.link_parent(surrogate.key)

				try:
					surrogate.finish(self.dataset.data["num_rows"])
				except RuntimeError:
					# already finished, could happen (though it shouldn't)
					pass

				surrogate.update_status(self.dataset.get_status())

			except ValueError:
				# dataset with key to attach to doesn't exist...
				self.log.warning("Cannot attach dataset chain containing %s to %s (dataset does not exist)" % (self.dataset.key, self.parameters["attach_to"]))

		self.job.finish()

	@abc.abstractmethod
	def process(self):
		"""
		Process scraped data

		:param data:  Parsed JSON data
		"""
		pass
