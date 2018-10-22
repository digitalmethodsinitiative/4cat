"""
Manager for a pool of workers

Also known as "employer"
"""
import importlib
import inspect
import signal
import glob
import time
import sys
import os

from backend.lib.worker import BasicWorker


class WorkerManager:
	"""
	Worker Manager

	Simple class that contains the main loop as well as a threaded keyboard poller
	that listens for a keypress (which can be used to end the main loop)
	"""
	looping = True
	pool = []
	worker_prototypes = []
	log = None

	def __init__(self, logger):
		"""
		Set up key poller
		"""
		signal.signal(signal.SIGTERM, self.abort)
		self.log = logger

		self.loop()

	def abort(self, signum=signal.SIGTERM, frame=None):
		"""
		End main loop

		Should be called after a SIGTERM is received - the two signal-related
		function arguments remain unused.

		:param signum:  Code of signal through which abort was triggered
		:param frame:  Context within which abort was triggered
		"""
		self.looping = False
		self.log.warning("Quitting after next loop.")

	def loop(self):
		"""
		Loop the worker manager

		Every few seconds, this checks if all worker types have enough workers of their type
		running, and if not new ones are started.

		If aborted, all workers are politely asked to abort too.
		"""
		while self.looping:
			self.load_worker_types()

			# start new workers, if needed
			for worker_type in self.worker_prototypes:
				active_workers = len(
					[worker for worker in self.pool if worker.__class__.__name__ == worker_type.__name__])
				if active_workers < worker_type.max_workers:
					for i in range(active_workers, worker_type.max_workers):
						self.log.info("Starting new worker (%s, %i/%i)" % (
							worker_type.__name__, active_workers + 1, worker_type.max_workers))
						active_workers += 1
						worker = worker_type(logger=self.log)
						worker.start()
						self.pool.append(worker)

			# remove references to finished workers
			for worker in self.pool:
				if not worker.is_alive():
					self.pool.remove(worker)

			self.log.debug("Running workers: %i" % len(self.pool))

			# check in five seconds if any workers died and need to be restarted (probably not!)
			time.sleep(5)

		# let all workers end
		self.log.info("Waiting for all workers to finish...")
		for worker in self.pool:
			worker.abort()

		for worker in self.pool:
			worker.join()

	def load_worker_types(self):
		"""
		See what worker types are available

		Looks for python files in the "workers" folder, then looks for classes that
		are a subclass of BasicWorker that are available in those files, and not an
		abstract class themselves. Classes that meet those criteria and have not been
		loaded yet are added to an internal list of available worker types.
		"""
		# check for worker files
		os.chdir(os.path.abspath(os.path.dirname(__file__)) + "/../workers")
		for file in glob.glob("*.py"):
			module = "backend.workers." + file[:-3]
			if module in sys.modules:
				continue

			importlib.import_module(module)
			members = inspect.getmembers(sys.modules[module])

			for member in members:
				if inspect.isclass(member[1]) and issubclass(member[1], BasicWorker) and not inspect.isabstract(
						member[1]):
					self.log.debug("Adding worker type %s" % member[0])
					self.worker_prototypes.append(member[1])