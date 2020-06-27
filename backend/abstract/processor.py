"""
Basic post-processor worker - should be inherited by workers to post-process results
"""
import traceback
import typing
import shutil
import abc
import csv
import os

from backend.abstract.worker import BasicWorker
from backend.lib.dataset import DataSet
from backend.lib.helpers import get_software_version
from backend.lib.exceptions import WorkerInterruptedException, ProcessorInterruptedException, ProcessorException

csv.field_size_limit(1024 * 1024 * 1024)


class BasicProcessor(BasicWorker, metaclass=abc.ABCMeta):
	"""
	Abstract post-processor class

	A post-processor takes a finished search query as input and processed its
	result in some way, with another result set as output. The input thus is
	a CSV file, and the output (usually) as well. In other words, the result of
	a post-processor run can be used as input for another post-processor
	(though whether and when this is useful is another question).
	"""
	db = None  # database handler
	dataset = None  # Dataset object representing the dataset to be created
	job = None  # Job object that requests the execution of this processor
	parent = None  # Dataset object to be processed, if applicable
	source_file = None  # path to dataset to be processed, if applicable

	description = "No description available"  # processor description, shown in web front-end
	category = "Other"  # processor category, for sorting in web front-end
	extension = "csv"  # extension of files created by this processor
	options = {}  # configurable options for this processor
	parameters = {}  # values for the processor's configurable options

	# Tumblr posts can overflow the regular limit, so double this.
	csv.field_size_limit(131072 * 2)

	def work(self):
		"""
		Process a dataset

		Loads dataset metadata, sets up the scaffolding for performing some kind
		of processing on that dataset, and then processes it. Afterwards, clean
		up.
		"""
		try:
			self.dataset = DataSet(key=self.job.data["remote_id"], db=self.db)
		except TypeError:
			# query has been deleted in the meantime. finish without error,
			# as deleting it will have been a conscious choice by a user
			self.job.finish()
			return

		if self.dataset.data.get("key_parent", None):
			# search workers never have parents (for now), so we don't need to
			# find out what the parent dataset is if it's a search worker
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

		if self.interrupted:
			return self.abort()

		if not self.dataset.is_finished():
			try:
				self.process()
				self.after_process()
			except WorkerInterruptedException:
				self.abort()
			except Exception as e:
				frames = traceback.extract_tb(e.__traceback__)
				frames = [frame.filename.split("/").pop() + ":" + str(frame.lineno) for frame in frames[1:]]
				location = "->".join(frames)
				
				# Not all datasets have parent keys
				if len(self.dataset.get_genealogy()) > 1:
					parent_key = " (via " + self.dataset.get_genealogy()[0].key + ")"
				else:
					parent_key = ""

				raise ProcessorException("Processor %s raised %s while processing dataset %s%s in %s:\n   %s\n" % (self.type, e.__class__.__name__, self.dataset.key, parent_key, location, str(e)))
		else:
			# dataset already finished, job shouldn't be open anymore
			self.log.warning("Job %s/%s was queued for a dataset already marked as finished, deleting..." % (self.job.data["jobtype"], self.job.data["remote_id"]))
			self.job.finish()


	def after_process(self):
		"""
		After processing, declare job finished
		"""
		if self.dataset.data["num_rows"] > 0:
			self.dataset.update_status("Dataset saved.")

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
			# copy the results to an arbitrary place that was passed
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
				self.log.warning("Cannot attach dataset chain containing %s to %s (dataset does not exist)" % (
				self.dataset.key, self.parameters["attach_to"]))

		self.job.finish()

	def abort(self):
		"""
		Abort dataset creation and clean up so it may be attempted again later
		"""
		# remove any result files that have been created so far
		if self.dataset.get_results_path().exists():
			os.unlink(str(self.dataset.get_results_path()))

		if self.dataset.get_temporary_path().exists():
			shutil.rmtree(str(self.dataset.get_temporary_path()))

		# we release instead of finish, since interrupting is just that - the
		# job should resume at a later point. Delay resuming by 10 seconds to
		# give 4CAT the time to do whatever it wants (though usually this isn't
		# needed since restarting also stops the spawning of new workers)
		self.dataset.update_status("Dataset processing interrupted. Retrying later.")

		if self.interrupted == self.INTERRUPT_RETRY:
			# retry later - wait at least 10 seconds to give the backend time to shut down
			self.job.release(delay=10)
		elif self.interrupted == self.INTERRUPT_CANCEL:
			# cancel job
			self.job.finish()

	def iterate_csv_items(self, path):
		"""
		A generator that iterates through a CSV file

		With every iteration, the processor's 'interrupted' flag is checked,
		and if set a ProcessorInterruptedException is raised, which by default
		is caught and subsequently stops execution gracefully.

		:param Path path: 	Path to csv file to read
		:return:
		"""

		with open(path, encoding="utf-8") as input:

			reader = csv.DictReader(input)

			for item in reader:
				if self.interrupted:
					raise ProcessorInterruptedException("Processor interrupted while iterating through CSV file")

				yield item

	def write_csv_items_and_finish(self, data):
		"""
		Write data as csv to results file and finish dataset

		Determines result file path using dataset's path determination helper
		methods. After writing results, the dataset is marked finished. Will
		raise a ProcessorInterruptedException if the interrupted flag for this
		processor is set while iterating.

		:param data: A list or tuple of dictionaries, all with the same keys
		"""
		if not (isinstance(data, typing.List) or isinstance(data, typing.Tuple)) or isinstance(data, str):
			raise TypeError("write_csv_items requires a list or tuple of dictionaries as argument")

		if not data:
			raise ValueError("write_csv_items requires a dictionary with at least one item")

		if not isinstance(data[0], dict):
			raise TypeError("write_csv_items requires a list or tuple of dictionaries as argument")

		self.dataset.update_status("Writing results file")
		with self.dataset.get_results_path().open("w", encoding="utf-8", newline='') as results:
			writer = csv.DictWriter(results, fieldnames=data[0].keys())
			writer.writeheader()

			for row in data:
				if self.interrupted:
					raise ProcessorInterruptedException("Interrupted while writing results file")
				writer.writerow(row)

		self.dataset.update_status("Finished")
		self.dataset.finish(len(data))

	def is_filter(self):
		"""
		Is this processor a filter?

		Filters do not produce their own dataset but replace the parent dataset
		instead.

		:todo: Make this a bit more robust than sniffing the processor category
		:return bool:
		"""
		return hasattr(self, "category") and self.category and "filter" in self.category.lower()

	@abc.abstractmethod
	def process(self):
		"""
		Process data

		To be defined by the child processor.
		"""
		pass
