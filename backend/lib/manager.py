"""
The heart of the app - manages jobs and workers
"""
import signal
import time

from backend import all_modules
from backend.lib.keyboard import KeyPoller
from backend.lib.exceptions import JobClaimedException


class WorkerManager:
	"""
	Manages the job queue and worker pool
	"""
	queue = None
	db = None
	log = None

	worker_pool = {}
	pool = []
	looping = True

	def __init__(self, queue, database, logger, as_daemon=True):
		"""
		Initialize manager

		:param queue:  Job queue
		:param database:  Database handler
		:param logger:  Logger object
		:param bool as_daemon:  Whether the manager is being run as a daemon
		"""
		self.queue = queue
		self.db = database
		self.log = logger

		if not as_daemon:
			# listen for input if running interactively
			self.key_poller = KeyPoller(manager=self)
			self.key_poller.start()
		else:
			signal.signal(signal.SIGTERM, self.abort)

		self.validate_datasources()

		# queue a job for the api handler so it will be run
		self.queue.add_job("api", remote_id="localhost")

		# queue corpus stats and snapshot generators for a daily run
		self.queue.add_job("corpus-stats", remote_id="localhost", interval=86400)
		self.queue.add_job("expire-datasets", remote_id="localhost", interval=300)

		# it's time
		self.loop()

	def delegate(self):
		"""
		Delegate work

		Checks for open jobs, and then passes those to dedicated workers, if
		slots are available for those workers.
		"""
		jobs = self.queue.get_all_jobs()

		num_active = sum([len(self.worker_pool[jobtype]) for jobtype in self.worker_pool])
		self.log.debug("Running workers: %i" % num_active)

		# clean up workers that have finished processing
		for jobtype in self.worker_pool:
			all_workers = self.worker_pool[jobtype]
			for worker in all_workers:
				if not worker.is_alive():
					worker.join()
					self.worker_pool[jobtype].remove(worker)

			del all_workers

		# check if workers are available for unclaimed jobs
		for job in jobs:
			jobtype = job.data["jobtype"]

			if jobtype in all_modules.workers:
				worker_info = all_modules.workers[jobtype]
				if jobtype not in self.worker_pool:
					self.worker_pool[jobtype] = []

				# if a job is of a known type, and that job type has open
				# worker slots, start a new worker to run it
				if len(self.worker_pool[jobtype]) < worker_info["max"]:
					try:
						self.log.debug("Starting new worker for job %s" % jobtype)
						job.claim()
						worker = worker_info["class"](logger=self.log, manager=self, job=job, modules=all_modules)
						worker.start()
						self.worker_pool[jobtype].append(worker)
					except JobClaimedException:
						# it's fine
						pass

		time.sleep(1)

	def loop(self):
		"""
		Main loop

		Constantly delegates work, until no longer looping, after which all
		workers are asked to stop their work. Once that has happened, the loop
		properly ends.
		"""
		while self.looping:
			self.delegate()

		self.log.info("Telling all workers to stop doing whatever they're doing...")
		for jobtype in self.worker_pool:
			for worker in self.worker_pool[jobtype]:
				if hasattr(worker, "request_abort"):
					worker.request_abort()
				else:
					worker.abort()

		# wait for all workers to finish
		self.log.info("Waiting for all workers to finish...")
		for jobtype in self.worker_pool:
			for worker in self.worker_pool[jobtype]:
				self.log.info("Waiting for worker %s..." % jobtype)
				worker.join()

		time.sleep(3)

		# abort
		self.log.info("Bye!")

	def validate_datasources(self):
		"""
		Validate data sources

		Logs warnings if not all information is precent for the configured data
		sources.
		"""
		for datasource in all_modules.datasources:
			if datasource + "-search" not in all_modules.workers:
				self.log.error("No search worker defined for datasource %s. Search queries will not be executed." % datasource)

	def abort(self, signal=None, stack=None):
		"""
		Stop looping the delegator and prepare for shutdown
		"""
		self.log.info("Received SIGTERM")
		self.looping = False
