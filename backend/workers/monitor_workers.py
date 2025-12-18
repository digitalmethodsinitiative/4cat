"""
Monitor active workers
"""

import logging
import sys

from backend.lib.worker import BasicWorker


class WorkerMonitor(BasicWorker):
    """
    Monitor active threads

    This writes a debug log message at an interval listing active 4CAT threads.
    It can be used to identify workers that do not terminate correctly or to
    know where a certain worker is stuck if it does not seem to progress. It
    also shows the 'native ID' of the thread which can be used to find it in
    e.g. htop or another process monitor to inspect it further.

    If the logging level of 4CAT is not set to DEBUG or lower, this worker does
    nothing.
    """

    type = "worker-monitor"
    max_workers = 1

    @classmethod
    def ensure_job(cls, config=None):
        """
        Run at an interval of 15 seconds.
        """
        return {"remote_id": "refresh-items", "interval": 15}

    def work(self):
        """
        Monitor active 4CAT threads
        """
        if self.log.logger.level > logging.DEBUG:
            # do nothing if we're not debugging
            return self.job.finish()

        # try to map active threads to 4CAT workers
        # and also get the 'native ID' which, at least on linux, is the pid of
        # the thread - allowing for further inspecting
        frames = sys._current_frames()
        thread_id_map = {}
        for worker_type, workers in self.manager.worker_pool.items():
            for worker in workers:
                thread_id_map[worker.ident] = f"{worker_type}/{worker.native_id}"

        monitor_msg = ""
        for thread_id, frame in frames.items():
            stack = []
            while frame:
                # each frame has a reference to the parent frame (if there is one)
                # traverse this stack to construct the actual call stack
                stack.append(
                    f"{frame.f_code.co_filename.split('/')[-1]}:{frame.f_lineno}:{frame.f_code.co_name}()"
                )
                frame = frame.f_back

            stack = " ← ".join(stack[:-1]) # ignore the very first frame which is never relevant
            
            if thread_id in thread_id_map:
                monitor_msg += f"\n  4CAT worker {thread_id_map[thread_id]} :: {stack}"
            elif thread_id == self.manager.ident:
                monitor_msg += f"\n  4CAT main loop :: {stack}"
            else:
                monitor_msg += f"\n  4CAT unknown thread {thread_id} :: {stack}"

        self.log.debug(f"Currently {len(frames):,} active 4CAT threads: {monitor_msg}")
        return self.job.finish()
