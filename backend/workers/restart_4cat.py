"""
Restart 4CAT and optionally upgrade it to the latest release
"""
import subprocess
import shlex
import sys
import os

from pathlib import Path

import common.config_manager as config

from backend.abstract.worker import BasicWorker
from common.lib.exceptions import WorkerInterruptedException


class FourcatRestarterAndUpgrader(BasicWorker):
    """
    Restart 4CAT and optionally upgrade it to the latest release

    Why implement this as a worker? Trying to have 4CAT restart itself leads
    to an interesting conundrum: it will not be able to report the outcome of
    the restart, because whatever bit of code is keeping track of that will be
    interrupted by restarting 4CAT.

    Using a worker has the benefit of it restarting after 4CAT restarts, so it
    can then figure out that 4CAT was just restarted and report the outcome. It
    then uses a log file to keep track of the results. The log file can then be
    used by other parts of 4CAT to see if the restart was successful.

    It does lead to another conundrum - what if due to some error, 4CAT never
    restarts? Then this worker will not be run again to report its own failure.
    There seem to be no clean ways around this, so anything watching the
    outcome of the worker probably needs to implement some timeout after which
    it is assumed that the restart/upgrade process failed catastrophically.
    """
    type = "restart-4cat"
    max_workers = 1

    def work(self):
        """
        Restart 4CAT and optionally upgrade it to the latest release
        """
        # figure out if we're starting the restart or checking the result
        # after 4cat has been restarted
        is_resuming = self.job.data["attempts"] > 0

        log_file = Path(config.get("PATH_ROOT"), config.get("PATH_LOGS"), "restart-backend.log")
        self.log.info("Restart worker initiated.")

        if is_resuming:
            # 4CAT was restarted
            # The log file is used by other parts of 4CAT to see how it went,
            # so use it to report the outcome.
            log_stream = log_file.open("a")
            log_stream.write("4CAT restarted.\n")
            version_file = Path(config.get("PATH_ROOT"), "config/.current-version")
            self.log.info("Restart worker resumed after restarting 4CAT, finishing log.")

            if version_file.exists():
                log_stream.write("4CAT is now running version %s.\n" % version_file.open().readline().strip())

            log_stream.write("[Worker] Success. 4CAT restarted and/or upgraded.\n")
            self.job.finish()

        else:
            log_stream = log_file.open("w")
            log_stream.write("Initiating 4CAT restart worker\n")
            self.log.info("New restart initiated.")

            # trigger a restart and/or upgrade
            # returns a JSON with a 'status' key and a message, the message
            # being the process output
            os.chdir(config.get("PATH_ROOT"))
            if self.job.data["remote_id"] == "upgrade":
                command = sys.executable + " helper-scripts/migrate.py --release --repository %s --yes --restart" % \
                          shlex.quote(config.get("4cat.github_url"))
            else:
                command = sys.executable + " 4cat-daemon.py --no-version-check force-restart"

            try:
                # the tricky part is that this command will interrupt the
                # daemon, i.e. this worker!
                # so we'll never get to actually send a response, if all goes
                # well. but the file descriptor that stdout is piped to remains
                # open, somehow, so we can use that to keep track of the output
                # stdin needs to be /dev/null here because else when 4CAT
                # restarts and we re-attempt to make a daemon, it will fail
                # when trying to close the stdin file descriptor of the
                # subprocess (man, that was a fun bug to hunt down)
                process = subprocess.Popen(shlex.split(command), cwd=config.get("PATH_ROOT"),
                                           stdout=log_stream, stderr=log_stream, stdin=subprocess.DEVNULL)

                while not self.interrupted:
                    # basically wait for either the process to quit or 4CAT to
                    # be restarted (hopefully the latter)
                    try:
                        process.wait(1)
                        break
                    except subprocess.TimeoutExpired:
                        pass

                if process.returncode is not None:
                    # if we reach this, 4CAT was never restarted, and so the job failed
                    log_stream.write("\nUnexpected outcome of restart call (%s).\n" % (repr(process.returncode)))

                    raise RuntimeError()
                else:
                    # interrupted before the process could finish (as it should)
                    self.log.info("Restart triggered. Restarting 4CAT.")
                    raise WorkerInterruptedException()

            except (RuntimeError, subprocess.CalledProcessError) as e:
                log_stream.write(str(e))
                log_stream.write("[Worker] Error while restarting 4CAT. The script returned a non-standard error code "
                                 "(see above). You may need to restart 4CAT manually.\n")
                self.log.error("Error restarting 4CAT. See %s for details." % log_stream.name)
                self.job.finish()
