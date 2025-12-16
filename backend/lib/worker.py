"""
Worker class that all workers should implement
"""
import subprocess
import traceback
import threading
import shutil
import time
import abc

from typing import Iterable

from common.lib.queue import JobQueue
from common.lib.database import Database
from common.lib.exceptions import WorkerInterruptedException, ProcessorException, ProcessorInterruptedException
from common.config_manager import ConfigWrapper

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

    #: Local configuration (used in processors)
    config = None

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
        self.queue = queue

        # ModuleCollector cannot be easily imported into a worker because it itself
        # imports all workers, so you get a recursive import that Python (rightly) blocks
        # so for workers, modules data is passed as a constructor argument
        self.modules = modules

    def run(self):
        """
        Run the worker

        This calls the `work()` method, quite simply, but adds some
        scaffolding to take care of any exceptions that occur during the
        execution of the worker. The exception is then logged and the worker
        is gracefully ended, but the job is *not* released to ensure that the
        job is not run again immediately (which would probably instantly crash
        in the exact same way).

        There is also some set-up to ensure that thread-unsafe objects such as
        the config reader are only initialised once in a threaded context, i.e.
        once this method is run.

        You can configure the `WARN_SLACK_URL` configuration variable to make
        reports of worker crashers be sent to a Slack channel, which is a good
        way to monitor a running 4CAT instance!
        """
        try:
            database_appname = "%s-%s" % (self.type, self.job.data["id"])
            self.config = ConfigWrapper(self.modules.config)
            self.db = Database(logger=self.log, appname=database_appname, dbname=self.config.DB_NAME, user=self.config.DB_USER, password=self.config.DB_PASSWORD, host=self.config.DB_HOST, port=self.config.DB_PORT)
            self.queue = JobQueue(logger=self.log, database=self.db) if not self.queue else self.queue
            self.work()

            # workers should usually finish their jobs by themselves, but if
            # the worker finished without errors, the job can be finished in
            # any case
            if not self.job.is_finished:
                self.job.finish()

        except WorkerInterruptedException:
            self.log.info("Worker %s interrupted - cancelling." % self.type)

            # interrupted - retry later or cancel job altogether?
            if self.interrupted == self.INTERRUPT_RETRY:
                self.job.release(delay=10)
            elif self.interrupted == self.INTERRUPT_CANCEL:
                self.job.finish()

            self.abort()
        except ProcessorException as e:
            self.log.error(str(e), frame=e.frame)
        except Exception as e:
            stack = traceback.extract_tb(e.__traceback__)
            frames = [frame.filename.split("/").pop() + ":" + str(frame.lineno) for frame in stack]
            location = "->".join(frames)
            self.log.error("Worker %s raised exception %s and will abort: %s at %s" % (self.type, e.__class__.__name__, str(e), location), frame=stack)
        finally:
            # Clean up after work successfully completed or terminates
            try:
                self.clean_up()
            except Exception as e:
                self.log.error("Worker %s clean-up raised exception %s: %s" % (self.type, e.__class__.__name__, str(e)), frame=traceback.extract_tb(e.__traceback__))

            try:
                # explicitly close database connection as soon as it's possible
                self.db.close()
            except Exception as e:
                try:
                    self.log.error("Worker %s database close raised exception %s: %s" % (self.type, e.__class__.__name__, str(e)), frame=traceback.extract_tb(e.__traceback__))
                except Exception:
                    pass  # log likely broken already
            
            # Explicitly close this thread's memcache client to avoid lingering sockets
            try:
                cfg = getattr(self.modules, "config", None)
                if cfg:
                    cfg.close_memcache()
            except Exception:
                pass

    def clean_up(self):
        """
        Clean up after a processor runs successfully or results in error.
        Workers should override this method to implement any procedures
        to run to clean up a worker; by default this does nothing.
        """
        pass

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

    def run_interruptable_process(self, command, exception_message: str="", wait_time: int=5, timeout: int=0, cleanup_paths: Iterable=[]) -> subprocess.Popen:
        """
        Run a process and monitor while worker is active

        This runs the process and, while it is running, monitors the
        worker's interrupt status; if the worker is interrupted, the process
        is stopped or killed. An optional timeout can also be given after which
        the process will be stopped or killed even if the worker has not been
        interrupted.

        The process is stopped by sending a SIGTERM, and then if that does not
        end the process, a SIGKILL.

        :param command:  Command to run
        :param exception_message:  Message for the
        ProcessorInterruptedException that is raised if the worker is
        interrupted while the process is running.
        :param int wait_time:  Seconds to wait for the process after sending
        SIGTERM before sending a SIGKILL, and then to wait again before logging
        an error if SIGKILL does not end the process.
        :param int timeout:  Optional timeout, in seconds. 0 for no timeout.
        :param Iterable cleanup_paths:  Paths to delete before raising a
        ProcessorInterruptedException. Will be deleted with shutil.rmtree.
        :return:
        """
        if type(command) is str:
            raise TypeError("Command for run_interruptable_process must be an iterable (see documentation for "
                            "subprocess.Popen)")

        if not exception_message:
            exception_message = f"Interrupted while running {command[0]}"

        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )

        start_time = time.time()
        while process.poll() is None:
            if self.interrupted > self.INTERRUPT_NONE or (timeout and time.time() > start_time + timeout):
                if self.interrupted == self.INTERRUPT_NONE:
                    self.log.info(f"Interruptable process {command[0]} for worker of type {self.type} timed out, "
                                  f"terminating")
                else:
                    self.log.info(f"Worker interrupted, asking interruptable process {command[0]} for worker "
                                   f"{self.type} to terminate...")

                # Try graceful stop first with SIGTERM
                # Wait briefly, then force kill if needed
                try:
                    process.terminate()

                    try:
                        process.wait(wait_time)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        try:
                            process.wait(wait_time)
                        except subprocess.TimeoutExpired:
                            self.log.error(f"Sent SIGKILL to process {process.pid} but process did not terminate! "
                                           f"Process was started by worker {self.type} with command "
                                           f"{' '.join(command)}")

                except Exception as e:
                    self.log.error(f"Failed to kill process {process.pid}: got exception {e}. Cleaning up and "
                                   f"interrupting worker anyway.")

                finally:
                    if cleanup_paths:
                        for path in cleanup_paths:
                            shutil.rmtree(path, ignore_errors=True)

                    raise ProcessorInterruptedException(exception_message)
            
            time.sleep(0.1)

        return process

    @abc.abstractmethod
    def work(self):
        """
        This is where the actual work happens

        Whatever the worker is supposed to do, it should happen (or be
        initiated from) this method. By default it does nothing, descending
        classes should implement this method.
        """
        pass

    @staticmethod
    def is_4cat_class():
        """
        Is this a 4CAT class?

        This is used to determine whether a class is a 4CAT worker or a
        processor. This method should always return True for workers.

        :return:  True
        """
        return True

    @staticmethod
    def is_4cat_processor():
        """
        Is this a 4CAT processor?

        This is used to determine whether a class is a 4CAT
        processor.

        :return:  False
        """
        return False