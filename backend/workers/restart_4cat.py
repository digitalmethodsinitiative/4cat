"""
Restart 4CAT and optionally upgrade it to the latest release
"""
import subprocess
import requests
import hashlib
import shlex
import json
import time
import uuid
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

        # this file will keep the output of the process started to restart or
        # upgrade 4cat
        log_file_backend = Path(config.get("PATH_ROOT"), config.get("PATH_LOGS"), "restart-backend.log")
        lock_file = Path(config.get("PATH_ROOT"), "config/restart.lock")

        # this file has the log of the restart worker itself and is checked by
        # the frontend to see how far we are
        log_file_restart = Path(config.get("PATH_ROOT"), config.get("PATH_LOGS"), "restart.log")
        log_stream_restart = log_file_restart.open("a")

        if not is_resuming:
            log_stream_restart.write("Initiating 4CAT restart worker\n")
            self.log.info("New restart initiated.")

            # this lock file will ensure that people don't start two
            # simultaneous upgrades or something
            with lock_file.open("w") as outfile:
                hasher = hashlib.blake2b()
                hasher.update(str(uuid.uuid4()).encode("utf-8"))
                outfile.write(hasher.hexdigest())

            # trigger a restart and/or upgrade
            # returns a JSON with a 'status' key and a message, the message
            # being the process output
            if log_file_backend.exists():
                log_file_backend.unlink()

            if self.job.data["remote_id"] == "upgrade":
                command = sys.executable + " helper-scripts/migrate.py --release --repository %s --yes --restart --output %s" % \
                          (shlex.quote(config.get("4cat.github_url")), shlex.quote(str(log_file_backend)))
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
                log_stream_backend = log_file_backend.open("a")
                self.log.info("Running command %s" % command)
                process = subprocess.Popen(shlex.split(command), cwd=config.get("PATH_ROOT"),
                                           stdout=log_stream_backend, stderr=log_stream_backend, stdin=subprocess.DEVNULL)

                while not self.interrupted:
                    # basically wait for either the process to quit or 4CAT to
                    # be restarted (hopefully the latter)
                    try:
                        process.wait(1)
                        log_stream_backend.close()
                        break
                    except subprocess.TimeoutExpired:
                        pass

                if process.returncode is not None:
                    # if we reach this, 4CAT was never restarted, and so the job failed
                    log_stream_restart.write("\nUnexpected outcome of restart call (%s).\n" % (repr(process.returncode)))

                    raise RuntimeError()
                else:
                    # interrupted before the process could finish (as it should)
                    self.log.info("Restart triggered. Restarting 4CAT.\n")
                    raise WorkerInterruptedException()

            except (RuntimeError, subprocess.CalledProcessError) as e:
                log_stream_restart.write(str(e))
                log_stream_restart.write("[Worker] Error while restarting 4CAT. The script returned a non-standard error code "
                                 "(see above). You may need to restart 4CAT manually.\n")
                self.log.error("Error restarting 4CAT. See %s for details." % log_stream_restart.name)
                lock_file.unlink()
                self.job.finish()

            finally:
                log_stream_restart.close()

        else:
            # 4CAT back-end was restarted - now check the results and make the
            # front-end restart or upgrade too
            self.log.info("Restart worker resumed after restarting 4CAT, restart successful.")
            log_stream_restart.write("4CAT restarted.\n")
            with Path(config.get("PATH_ROOT"), "config/.current-version").open() as infile:
                log_stream_restart.write("4CAT is now running version %s.\n" % infile.readline().strip())

            if log_file_backend.exists():
                # copy output of started process to restart log
                with log_file_backend.open() as infile:
                    log_stream_restart.write(infile.read() + "\n")

                log_file_backend.unlink()

            # we're gonna use some specific Flask routes to trigger this, i.e.
            # we're interacting with the front-end through HTTP
            api_host = "https://" if config.get("flask.https") else "http://"
            api_host += "4cat_frontend:5000" if config.get("USING_DOCKER") else config.get("flask.server_name")

            if self.job.data["remote_id"] == "upgrade" and config.get("USING_DOCKER"):
                # when using Docker, the front-end needs to update separately
                log_stream_restart.write("Telling front-end Docker container to upgrade...\n")
                log_stream_restart.close()  # close, because front-end will be writing to it
                upgrade_ok = False
                upgrade_timeout = False
                try:
                    upgrade_url = api_host + "/admin/trigger-frontend-upgrade/"
                    with lock_file.open() as infile:
                        frontend_upgrade = requests.post(upgrade_url, data={"token": infile.read()}, timeout=(10 * 60))
                    upgrade_ok = frontend_upgrade.json()["status"] == "OK"
                except requests.RequestException:
                    pass
                except TimeoutError:
                    upgrade_timeout = True

                log_stream_restart = log_file_restart.open("a")
                if not upgrade_ok:
                    if upgrade_timeout:
                        log_stream_restart.write("Upgrade timed out.")
                    log_stream_restart.write("Error upgrading front-end container. You may need to upgrade and restart"
                                             "containers manually.\n")
                    lock_file.unlink()
                    return self.job.finish()

            # restart front-end
            log_stream_restart.write("Asking front-end to restart itself...\n")
            log_stream_restart.flush()
            try:
                restart_url = api_host + "/admin/trigger-frontend-restart/"
                with lock_file.open() as infile:
                    response = requests.post(restart_url, data={"token": infile.read()}, timeout=5).json()

                if response.get("message"):
                    log_stream_restart.write(response.get("message") + "\n")
            except (json.JSONDecodeError, requests.RequestException):
                # this may happen because the server restarts and interrupts
                # the request
                pass

            # wait for front-end to come online after a restart
            time.sleep(3)  # give some time for the restart to trigger
            start_time = time.time()
            frontend_ok = False
            while time.time() < start_time + 60:
                try:
                    frontend = requests.get(api_host + "/", timeout=5)
                    if frontend.status_code != 200:
                        time.sleep(2)
                        continue
                    frontend_ok = True
                    break
                except requests.RequestException as e:
                    time.sleep(1)
                    continue

            # too bad
            if not frontend_ok:
                log_stream_restart.write("Timed out waiting for front-end to restart. You may need to restart it "
                                         "manually.\n")
                self.log.error("Front-end did not come back online after restart")
            else:
                log_stream_restart.write("Front-end is available. Restart complete.")
                self.log.info("Front-end is available. Restart complete.")

            log_stream_restart.close()
            lock_file.unlink()
            self.job.finish()
