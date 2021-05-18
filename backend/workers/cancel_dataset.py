"""
Delete and cancel a dataset
"""
from backend.abstract.worker import BasicWorker
from common.lib.exceptions import JobNotFoundException
from common.lib.dataset import DataSet
from common.lib.job import Job


class DatasetCanceller(BasicWorker):
	"""
	Cancel a dataset's creation and delete it

	Datasets can be deleted quite easily, but this becomes harder if one wants
	to delete them while they're being created. This worker, given a dataset's
	key, can take care of this.
	"""
	type = "cancel-dataset"
	max_workers = 1

	def work(self):
		"""
		Send pg_cancel_backend query to cancel query with given PID
		"""

		# delete dataset
		try:
			dataset = DataSet(key=self.job.data["remote_id"], db=self.db)
			jobtype = dataset.data["type"]
		except TypeError:
			# dataset already deleted, apparently
			self.job.finish()
			return

		# now find the job that's tasked with creating this dataset, if it
		# exists
		try:
			job = Job.get_by_remote_ID(remote_id=self.job.data["remote_id"], jobtype=jobtype, database=self.db)
		except JobNotFoundException:
			# no job... dataset already fully finished?
			self.job.finish()
			return

		# ask the manager to interrupt this job
		self.manager.request_interrupt(job, self.INTERRUPT_CANCEL)

		# done
		self.job.finish()
