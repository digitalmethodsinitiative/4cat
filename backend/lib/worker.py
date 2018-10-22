"""
Worker class that all workers should implement
"""
import traceback
import threading
import time
import abc

from backend.lib.queue import JobQueue
from backend.lib.database import Database


class BasicWorker(threading.Thread, metaclass=abc.ABCMeta):
	"""
	Abstract Worker class

	This starts a separate thread in which a worker method is continually called until
	the worker is told to stop working. The work method can do whatever the worker needs
	to do - that part is to be implemented by a child class.
	"""
	type = "misc"  # this should match the job type as saved in the database
	jobdata = {}
	pause = 1  # time to wait between scrapes
	max_workers = 1  # max amount of workers of this type

	queue = None
	log = None
	looping = True
	loop_time = 0

	def __init__(self, logger, db=None, queue=None):
		"""
		Basic init, just make sure our thread name is meaningful

		:param Database db:  Database connection - if not given, a new one will be created
		:param JobQueue queue: Job Queue - if not given, a new one will be instantiated
		"""
		super().__init__()
		self.name = self.type
		self.log = logger

		self.db = Database(logger=self.log) if not db else db
		self.queue = JobQueue(logger=self.log, database=self.db) if not queue else queue

	def abort(self):
		"""
		Stop the work loop, and end the thread.
		"""
		self.looping = False

	def run(self):
		"""
		Loop the worker

		This simply calls the work method continually, with a pause in-between calls.
		"""
		while self.looping:
			self.loop_time = int(time.time())

			try:
				self.work()
			except Exception as e:
				frames = traceback.extract_tb(e.__traceback__)
				frames = [frame.filename.split("/").pop() + ":" + str(frame.lineno) for frame in frames]
				location = "->".join(frames)
				self.log.error("Worker %s raised exception %s and will abort: %s at %s" % (self.type, e.__class__.__name__, e, location))
				self.abort()

			time.sleep(self.pause)

	@abc.abstractmethod
	def work(self):
		"""
		This is where the actual work happens

		Whatever the worker is supposed to do, it should happen (or be initiated from) this
		method, which is looped indefinitely until the worker is told to finish.
		"""
		pass
