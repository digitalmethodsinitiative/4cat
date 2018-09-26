import importlib
import inspect
import glob
import time
import sys
import os

from lib.keyboard import KeyPoller
from lib.logger import Logger
from lib.worker import BasicWorker

from config import config


class WorkerManager:
    """
    Worker Manager

    Simple class that contains the main loop as well as a threaded keyboard poller
    that listens for a keypress (which can be used to end the main loop)
    """
    looping = True
    key_poller = None
    pool = []
    worker_prototypes = []

    def __init__(self):
        """
        Set up key poller
        """
        self.key_poller = KeyPoller(self)
        self.log = Logger()
        self.loop()

    def abort(self):
        """
        End main loop
        """
        self.looping = False
        self.log.info("Quitting after next loop.")

    def loop(self):
        """
        Loop the worker manager

        Every few seconds, this checks if all worker types have enough workers of their type
        running, and if not new ones are started.

        If aborted, all workers are politely asked to abort too.
        """
        while self.looping:
            self.load_worker_types()

            # start new workers, if neededz
            for worker_type in self.worker_prototypes:
                active_workers = len([worker for worker in self.pool if worker.__class__.__name__ == worker_type.__name__])
                if active_workers < worker_type.max_workers:
                    for i in range(active_workers, worker_type.max_workers):
                        self.log.info("Starting new worker (%s, %i/%i)" % (worker_type.__name__, active_workers + 1, worker_type.max_workers))
                        active_workers += 1
                        worker = worker_type()
                        worker.start()
                        self.pool.append(worker)

            # remove references to finished workers
            for worker in self.pool:
                if not worker.is_alive():
                    self.pool.remove(worker)

            self.log.info("Running workers: %i" % len(self.pool))

            # check in five seconds if any workers died and need to be restarted (probably not!)
            time.sleep(5)

        # let all workers end
        print("Waiting for all workers to finish...")
        for worker in self.pool:
            worker.abort()

        for worker in self.pool:
            worker.join()

        print("Done!")

    def load_worker_types(self):
        """
        See what worker types are available

        Looks for python files in the "workers" folder, then looks for classes that
        are a subclass of BasicWorker that are available in those files, and not an
        abstract class themselves. Classes that meet those criteria and have not been
        loaded yet are added to an internal list of available worker types.
        """
        # check for worker files
        os.chdir("workers")
        for file in glob.glob("*.py"):
            module = "workers." + file[:-3]
            if module in sys.modules:
                continue

            importlib.import_module(module)
            members = inspect.getmembers(sys.modules[module])

            for member in members:
                if inspect.isclass(member[1]) and issubclass(member[1], BasicWorker) and not inspect.isabstract(member[1]):
                    self.worker_prototypes.append(member[1])

        os.chdir("..")