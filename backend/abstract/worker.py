"""
Worker class that all workers should implement
"""
import traceback
import threading
import time
import abc

from common.lib.queue import JobQueue
from common.lib.database import Database
from common.lib.exceptions import WorkerInterruptedException, ProcessorException


class BasicWorker(threading.Thread, metaclass=abc.ABCMeta):
	"""
	Abstract Worker class

	This runs as a separate thread in which a worker method is executed. The
	work method can do whatever the worker needs to do - that part is to be
	implemented by a child class. This class provides scaffolding that makes
	sure crashes are caught properly and the relevant data is available to the
	worker code.
	"""
	#: Worker type - should match Job ID used when queuing jobs
	type = "misc"

	#: Amount of workers of this type that can run in parallel. Be careful with
	#: this, because values higher than 1 will mean that e.g. API rate limits
	#: are easily violated.
	max_workers = 1

	#: Flag value to indicate worker interruption type - not interrupted
	INTERRUPT_NONE = False

	#: Flag value to indicate worker interruption type - interrupted, but can
	#: be retried
	INTERRUPT_RETRY = 1

	#: Flag value to indicate worker interruption type - interrupted, but
	#: should be cancelled
	INTERRUPT_CANCEL = 2

	#: Job queue that can be used to create or manipulate jobs
	queue = None

	#: Job this worker is being run for
	job = None

	#: Logger object
	log = None

	#: WorkerManager that manages this worker
	manager = None

	#: Interrupt status, one of the `INTERRUPT_` class constants
	interrupted = False

	#: Module index
	modules = None

	#: Unix timestamp at which this worker was started
	init_time = 0

	def __init__(self, logger, job, queue=None, manager=None, modules=None):
		"""
		Worker init

		Set up object attributes, e.g. the worker queue and manager, and
		initialize a new database connection and connected job queue. We cannot
		share database connections between workers because they are not
		thread-safe.

		:param Logger logger:  Logging interface
		:param Job job:  Job this worker is being run on
		:param JobQueue queue:  Job queue
		:param WorkerManager manager:  Scheduler instance that started this worker
		:param modules:  Module catalog
		"""
		super().__init__()
		self.name = self.type
		self.log = logger
		self.manager = manager
		self.job = job
		self.init_time = int(time.time())

		# all_modules cannot be easily imported into a worker because all_modules itself
		# imports all workers, so you get a recursive import that Python (rightly) blocks
		# so for workers, all_modules' content is passed as a constructor argument
		self.all_modules = modules

		database_appname = "%s-%s" % (self.type, self.job.data["id"])
		self.db = Database(logger=self.log, appname=database_appname)
		self.queue = JobQueue(logger=self.log, database=self.db) if not queue else queue

	def run(self):
		"""
		Run the worker

		This calls the `work()` method, quite simply, but adds some
		scaffolding to take care of any exceptions that occur during the
		execution of the worker. The exception is then logged and the worker
		is gracefully ended, but the job is *not* released to ensure that the
		job is not run again immediately (which would probably instantly crash
		in the exact same way).

		You can configure the `WARN_SLACK_URL` configuration variable to make
		reports of worker crashers be sent to a Slack channel, which is a good
		way to monitor a running 4CAT instance!
		"""
		try:
			self.work()
		except WorkerInterruptedException:
			self.log.info("Worker %s interrupted - cancelling." % self.type)

			# interrupted - retry later or cancel job altogether?
			if self.interrupted == self.INTERRUPT_RETRY:
				self.job.release(delay=10)
			elif self.interrupted == self.INTERRUPT_CANCEL:
				self.job.finish()

			self.abort()
		except ProcessorException as e:
			self.log.error(str(e))
			self.job.add_status("Crash during execution")
		except Exception as e:
			frames = traceback.extract_tb(e.__traceback__)
			frames = [frame.filename.split("/").pop() + ":" + str(frame.lineno) for frame in frames]
			location = "->".join(frames)
			self.log.error("Worker %s raised exception %s and will abort: %s at %s" % (self.type, e.__class__.__name__, str(e), location))
			self.job.add_status("Crash during execution")

	def abort(self):
		"""
		Called when the application shuts down

		Can be used to stop loops, for looping workers. Workers should override
		this method to implement any procedures to run to clean up a worker
		when it is interrupted; by default this does nothing.
		"""
		pass

	def request_interrupt(self, level=1):
		"""
		Set the 'abort requested' flag

		Child workers should quit at their earliest convenience when this is
		set. This can be done simply by checking the value of
		`self.interrupted`.

		:param int level:  Retry or cancel? Either `self.INTERRUPT_RETRY` or
		  `self.INTERRUPT_CANCEL`.
		"""
		self.log.debug("Interrupt requested for worker %s/%s" % (self.job.data["jobtype"], self.job.data["remote_id"]))
		self.interrupted = level

	@abc.abstractmethod
	def work(self):
		"""
		This is where the actual work happens

		Whatever the worker is supposed to do, it should happen (or be
		initiated from) this method. By default it does nothing, descending
		classes should implement this method.
		"""
		pass
