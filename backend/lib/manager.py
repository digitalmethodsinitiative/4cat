"""
The heart of the app - manages jobs and workers
"""
import threading
import signal
import time

from collections.abc import Generator

from backend.lib.proxied_requests import DelegatedRequestHandler
from backend.lib.worker import BasicWorker
from common.lib.exceptions import JobClaimedException

# for now, this is hardcoded - could be dynamic or depending on the queue ID in
# the future
MAX_JOBS_PER_QUEUE = 1

class WorkerManager:
	"""
	Manages the job queue and worker pool
	"""
	queue = None
	db = None
	log = None
	modules = None
	proxy_delegator = None

	worker_pool = {}
	job_mapping = {}
	pool = []
	looping = True
	unknown_jobs = set()

	def __init__(self, queue, database, logger, modules, as_daemon=True):
		"""
		Initialize manager

		:param queue:  Job queue
		:param database:  Database handler
		:param logger:  Logger object
		:param modules:  Modules cache via ModuleLoader()
		:param bool as_daemon:  Whether the manager is being run as a daemon
		"""
		self.queue = queue
		self.db = database
		self.log = logger
		self.modules = modules
		self.proxy_delegator = DelegatedRequestHandler(self.log, self.modules.config)

		if as_daemon:
			signal.signal(signal.SIGTERM, self.abort)

		# datasources are initialized here; the init_datasource functions found in their respective __init__.py files
		# are called which, in the case of scrapers, also adds the scrape jobs to the queue.
		self.validate_datasources()

		# queue jobs for workers that always need one
		for worker_name, worker in self.modules.workers.items():
			if hasattr(worker, "ensure_job"):
				# ensure_job is a class method that returns a dict with job parameters if job should be added
				# pass config for some workers (e.g., web studies extensions)
				try:
					self.log.debug(f"Ensuring job exists for worker {worker_name}")
					job_params = worker.ensure_job(config=self.modules.config)
				except Exception as e:
					self.log.error(f"Error while ensuring job for worker {worker_name}: {e}")
					job_params = None

				if job_params:
					self.queue.add_job(worker_or_type=worker, **job_params)

		self.ident = threading.get_ident()
		self.log.info("4CAT Started")

		# flush module collector log buffer
		# the logger is not available when this initialises
		# but it is now!
		if self.modules.log_buffer:
			self.log.warning(self.modules.log_buffer)
			self.modules.log_buffer = ""

		# it's time
		self.loop()

	def delegate(self):
		"""
		Delegate work

		Checks for open jobs, and then passes those to dedicated workers, if
		slots are available for those workers.
		"""
		jobs = self.queue.get_all_jobs()

		num_active = len(list(self.iterate_active_workers()))
		self.log.debug2(f"Running {num_active} active workers")

		# clean up workers that have finished processing
		# not using iterate_active_workers() here because we're going to change
		# the dictionary while iterating through it
		for queue_id in self.worker_pool:
			all_workers = self.worker_pool[queue_id]
			for worker in all_workers:
				if not worker.is_alive():
					self.log.debug(f"Terminating worker {worker.job.data['jobtype']}/{worker.job.data['remote_id']}")
					worker.join()
					self.worker_pool[queue_id].remove(worker)

			del all_workers

		# check if workers are available for unclaimed jobs
		for job in jobs:
			queue_id = job.data["queue_id"]
			jobtype = job.data["jobtype"]

			if jobtype in self.modules.workers:
				worker_class = self.modules.workers[jobtype]
				if queue_id not in self.worker_pool:
					self.worker_pool[queue_id] = []

				# if a job is of a known type, and that job type has open
				# worker slots, start a new worker to run it
				if len(self.worker_pool[queue_id]) < MAX_JOBS_PER_QUEUE:
					try:
						worker_available = worker_class.check_worker_available(manager=self, modules=self.modules)
					except Exception as e:
						self.log.error(f"Error checking if worker {jobtype} is available: {e}")
						worker_available = False
					if not worker_available:
						self.log.debug(f"Worker {jobtype} is not currently available, skipping...")
						continue
					try:
						job.claim()
						worker = worker_class(logger=self.log, manager=self, job=job, modules=self.modules)
						worker.start()
						log_level = self.log.levels["DEBUG"] if job.data["interval"] else self.log.levels["INFO"]
						self.log.log(f"Starting new worker for job {job.data['jobtype']}/{job.data['remote_id']}", log_level)
						self.worker_pool[queue_id].append(worker)
					except JobClaimedException:
						# it's fine
						pass
			else:
				if jobtype not in self.unknown_jobs:
					self.log.error(f"Unknown job type: {jobtype}")
					self.unknown_jobs.add(jobtype)

		time.sleep(1)

	def loop(self):
		"""
		Main loop

		Constantly delegates work, until no longer looping, after which all
		workers are asked to stop their work. Once that has happened, the loop
		properly ends.
		"""
		while self.looping:
			try:
				self.delegate()
			except KeyboardInterrupt:
				self.looping = False

		self.log.info("Telling all workers to stop doing whatever they're doing...")

		# request shutdown from all workers except the API
		# this allows us to use the API to figure out if a certain worker is
		# hanging during shutdown, for example
		for queue_id, worker in self.iterate_active_workers():
			if worker.type == "api":
				continue

			if hasattr(worker, "request_interrupt"):
				worker.request_interrupt()
			else:
				worker.abort()

		# wait for all workers that we just asked to quit to finish
		self.log.info("Waiting for all workers to finish...")
		for queue_id, worker in self.iterate_active_workers():
			if worker.type == "api":
				continue

			self.log.info(f"Waiting for worker of type {worker.type}...")
			worker.join()

		# shut down any remaining workers (i.e. the API)
		for queue_id, worker in self.iterate_active_workers():
			worker.request_interrupt()
			worker.join()

		# abort
		time.sleep(1)
		self.log.info("Bye!")

	def validate_datasources(self):
		"""
		Validate data sources

		Logs warnings if not all information is present for the configured data
		sources.
		"""
		for datasource in self.modules.datasources:
			if datasource + "-search" not in self.modules.workers and datasource + "-import" not in self.modules.workers:
				self.log.error(f"No search worker defined for data source {datasource} or its modules are missing. "
				               f"Datasets cannot be created for it.")

			self.modules.datasources[datasource]["init"](self.db, self.log, self.queue, datasource, self.modules.config)

	def abort(self, signal=None, stack=None):
		"""
		Stop looping the delegator, clean up, and prepare for shutdown
		"""
		self.log.info("Received SIGTERM")

		# cancel all interruptible postgres queries
		# this needs to be done before we stop looping since after that no new
		# jobs will be claimed, and needs to be done here because the worker's
		# own database connection is busy executing the query that it should
		# cancel! so we can't use it to update the job and make it get claimed
		for job in self.queue.get_all_jobs("cancel-pg-query", restrict_claimable=False):
			# this will make all these jobs immediately claimable, i.e. queries
			# will get cancelled asap
			self.log.debug("Cancelling interruptable Postgres queries for connection %s..." % job.data["remote_id"])
			job.claim()
			job.release(delay=0, claim_after=0)

		# wait until all cancel jobs are completed
		while self.queue.get_all_jobs("cancel-pg-query", restrict_claimable=False):
			time.sleep(0.25)

		# now stop looping (i.e. accepting new jobs)
		self.looping = False

	def request_interrupt(self, interrupt_level, job):
		"""
		Interrupt a specific job

		This method can be called via e.g. the API, to interrupt a specific
		job's worker. The worker for the given Job object is searched for and
		if it exists, its `request_interrupt()` method is called.

		:param int interrupt_level:  Retry later or cancel?
		:param Job job:  Job object to cancel worker for
		"""
		for queue_id, worker in self.iterate_active_workers():
			if worker.job.data["id"] == job.data["id"]:
				# first cancel any interruptable postgres queries for this job's worker
				while True:
					active_queries = self.queue.get_all_jobs("cancel-pg-query", remote_id=worker.db.appname, restrict_claimable=False)
					if not active_queries:
						# all cancellation jobs have been run
						break

					for cancel_job in active_queries:
						if cancel_job.is_claimed:
							continue

						# this will cause the job be run asap
						cancel_job.claim()
						cancel_job.release(delay=0, claim_after=0)

					# give the cancel job a moment to run
					time.sleep(0.25)

				# now all queries are interrupted, formally request an abort
				self.log.info(f"Requesting interrupt of job {worker.job.data['id']} ({worker.job.data['jobtype']}/{worker.job.data['remote_id']})")
				worker.request_interrupt(interrupt_level)
				return

	def iterate_active_workers(self) -> Generator[tuple[str, BasicWorker]]:
		"""
		Return all active workers

		Convenience function to avoid having to always use two nested for
		loops.

		:return:  Generator that yields tuples of (queue_id, worker)
		"""
		for queue_id in self.worker_pool:
			for worker in self.worker_pool[queue_id]:
				yield queue_id, worker