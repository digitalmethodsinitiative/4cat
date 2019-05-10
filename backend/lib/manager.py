"""
The heart of the app - manages jobs and workers
"""
import importlib
import inspect
import signal
import time
import glob
import sys
import os
import re

import config

from backend.abstract.worker import BasicWorker
from backend.lib.keyboard import KeyPoller
from backend.lib.exceptions import JobClaimedException


class WorkerManager:
	"""
	Manages the job queue and worker pool
	"""
	queue = None
	db = None
	log = None

	worker_map = {}
	worker_pool = {}
	datasources = {}
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

		self.load_workers()
		self.validate_datasources()

		# queue a job for the api handler so it will be run
		self.queue.add_job("api", remote_id="localhost")

		# queue corpus stats and snapshot generators for a daily run
		self.queue.add_job("corpus-stats", remote_id="localhost", interval=86400)
		if config.PATH_SNAPSHOTDATA and os.path.exists(config.PATH_SNAPSHOTDATA):
			self.queue.add_job("schedule-snapshot", remote_id="localhost", interval=60)

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
			if jobtype in self.worker_map:
				worker_info = self.worker_map[jobtype]
				if jobtype not in self.worker_pool:
					self.worker_pool[jobtype] = []

				# if a job is of a known type, and that job type has open
				# worker slots, start a new worker to run it
				if len(self.worker_pool[jobtype]) < worker_info["max"]:
					try:
						self.log.debug("Starting new worker for job %s" % jobtype)
						job.claim()
						worker = worker_info["class"](logger=self.log, manager=self, job=job)
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

	def load_workers(self):
		"""
		Looks for files containing worker definitions and import those as
		modules

		Futhermore calls the init method of any datasources found (if they
		have such a method)
		"""
		self.log.debug("Loading workers...")
		base = os.path.abspath(os.path.dirname(__file__) + "../../..")

		# folders with generic workers
		folders = ["backend/postprocessors", "backend/workers"]

		# add folders with datasource-specific workers
		os.chdir(base + "/datasources")
		datasources = [file[:-1] for file in glob.glob("**/**/")] + [file[:-1] for file in glob.glob("**/")]
		for datasource in datasources:
			folders.append("datasources/%s" % datasource)

		# load any workers found in those folders
		for folder in folders:
			os.chdir(base + "/" + folder)
			files = glob.glob("./*.py")
			for file in files:
				if file[2:4] == "__":
					# we're not interested in __init__.py etc
					continue

				# initialize data source if it's the first time encountering it
				if "datasources" in folder:
					datasource = folder.split("datasources/")[1]
					datasource = re.split(r"[\\\/]", datasource)[0]
					if datasource not in self.datasources:
						self.log.info("(Startup) Registered data source %s" % datasource)
						datamodule = "datasources." + folder.replace(base, "")[12:]
						datamodule = re.split(r"[\\\/]", datamodule)[0]

						importlib.import_module(datamodule)

						# initialize datasource
						datasource_id = datasource
						if hasattr(sys.modules[datamodule], "init_datasource") and hasattr(sys.modules[datamodule], "PLATFORM"):
							self.log.debug("Initializing datasource %s" % datasource)
							datasource_id = sys.modules[datamodule].PLATFORM
							sys.modules[datamodule].init_datasource(logger=self.log, database=self.db, queue=self.queue, name=sys.modules[datamodule].PLATFORM)
						else:
							self.log.error("Datasource %s is lacking init_datasource or PLATFORM in __init__.py" % datasource)

						self.datasources[datasource_id] = datasource

					module = folder.replace(base, "").replace("\\", ".").replace("/", ".") + "." + file[2:-3]
					if module in sys.modules:
						# we've been here
						continue

				else:
					# load relevant files in folder
					module = folder.replace("\\", ".").replace("/", ".") + "." + file[2:-3]
					if module in sys.modules:
						# already loaded
						continue

				# now check if the file is actually a worker or just a random python file we
				# accidentally loaded (in which case it will be garbage collected)
				importlib.import_module(module)
				members = inspect.getmembers(sys.modules[module])
				for member in members:
					if member[0][0:2] == "__" or not inspect.isclass(member[1]) or not issubclass(member[1], BasicWorker) or inspect.isabstract(
							member[1]):
						# is not a valid worker definition
						continue

					if member[1].type in self.worker_map:
						# already mapped
						continue

					# save to worker map
					worker = {
						"max": member[1].max_workers,
						"name": member[0],
						"jobtype": member[1].type,
						"class": member[1]
					}
					self.log.info("Adding worker type %s" % member[0])
					self.worker_map[member[1].type] = worker

	def validate_datasources(self):
		"""
		Validate data sources

		Logs warnings if not all information is precent for the configured data
		sources.
		"""
		for datasource in self.datasources:
			if datasource + "-search" not in self.worker_map:
				self.log.error("No search worker defined for datasource %s. Search queries will not be executed." % datasource)

			if datasource + "-thread" not in self.worker_map:
				self.log.warning("No thread scraper defined for datasource %s." % datasource)

			if datasource + "-board" not in self.worker_map:
				self.log.warning("No board scraper defined for datasource %s." % datasource)

	def abort(self, signal=None, stack=None):
		"""
		Stop looping the delegator and prepare for shutdown
		"""
		self.log.info("Received SIGTERM")
		self.looping = False
