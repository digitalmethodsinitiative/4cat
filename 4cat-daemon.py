import subprocess
import argparse
import time
import sys
import os
import re

from pathlib import Path

cli = argparse.ArgumentParser()
cli.add_argument("--interactive", "-i", default=False, help="Run 4CAT in interactive mode (not in the background).",
                 action="store_true")
cli.add_argument("--log-level", "-l", default="INFO", help="Set log level (\"DEBUG\", \"INFO\", \"WARNING\", \"ERROR\", \"CRITICAL\", \"FATAL\").")
cli.add_argument("--no-version-check", "-n", default=False,
                 help="Skip version check that may prompt the user to migrate first.", action="store_true")
cli.add_argument("command")
args = cli.parse_args()

# ---------------------------------------------
#  first-run.py ensures everything is set up
#  right when running 4CAT for the first time
# ---------------------------------------------
first_run = Path(__file__).parent.joinpath("helper-scripts", "first-run.py")
result = subprocess.run([sys.executable, str(first_run)], stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE)

if result.returncode != 0:
    print("Unexpected error while preparing 4CAT. You may need to re-install 4CAT.")
    print("stdout:\n" + "\n".join(["  " + line for line in result.stdout.decode("utf-8").split("\n")]))
    print("stderr:\n" + "\n".join(["  " + line for line in result.stderr.decode("utf-8").split("\n")]))
    exit(1)

# ---------------------------------------------
#     Do not start if migration is required
# ---------------------------------------------
if not args.no_version_check:
    target_version_file = Path("VERSION")
    current_version_file = Path("config/.current-version")

    if not current_version_file.exists():
        # this is the latest version lacking version files
        current_version = "1.9"
    else:
        with current_version_file.open() as handle:
            current_version = re.split(r"\s", handle.read())[0].strip()

    if not target_version_file.exists():
        target_version = "1.9"
    else:
        with target_version_file.open() as handle:
            target_version = re.split(r"\s", handle.read())[0].strip()

    if current_version != target_version:
        print("Migrated version: %s" % current_version)
        print("Code version: %s" % target_version)
        print("Upgrade detected. You should run the following command to update 4CAT before (re)starting:")
        print("  %s helper-scripts/migrate.py" % sys.executable)
        exit(1)

# we can only import this here, because the version check above needs to be
# done first, as it may detect that the user needs to migrate first before
# the config manager can be run properly
from common.config_manager import config
from common.lib.helpers import call_api
# ---------------------------------------------
#     Check validity of configuration file
# (could be expanded to check for other values)
# ---------------------------------------------
if not config.get('ANONYMISATION_SALT') or config.get('ANONYMISATION_SALT') == "REPLACE_THIS":
    print(
        "You need to set a random value for anonymisation in config.py before you can run 4CAT. Look for the ANONYMISATION_SALT option.")
    sys.exit(1)

# ---------------------------------------------
#   Running as a daemon is only supported on
#   POSIX-compatible systems - run interactive
#                on Windows.
# ---------------------------------------------
if os.name not in ("posix",):
    # if not, run the backend directly and quit
    print("Using '%s' to run the 4CAT backend is only supported on UNIX-like systems." % __file__)
    print("Running backend in interactive mode instead.")
    import backend.bootstrap as bootstrap

    bootstrap.run(as_daemon=False, log_level=args.log_level)
    sys.exit(0)

if args.interactive:
    print("Running backend in interactive mode.")
    import backend.bootstrap as bootstrap

    bootstrap.run(as_daemon=False, log_level=args.log_level)
    sys.exit(0)
else:
    # if so, import necessary modules
    import psutil
    import daemon

# determine PID file
pidfile = config.get('PATH_ROOT').joinpath(config.get('PATH_LOCKFILE'), "4cat.pid")  # pid file location

# ---------------------------------------------
#   These functions start and stop the daemon
# ---------------------------------------------
# These are only defined at this point because they require the psutil and
# daemon modules which are not available on Windows.
def start():
    """
    Start backend, as a daemon
    :return bool: True
    """
    # only one instance may be running at a time
    if pidfile.is_file():
        with pidfile.open() as infile:
            pid = int(infile.read().strip())

        if pid in psutil.pids():
            print("...error: the 4CAT Backend Daemon is already running.")
            return False

    # start daemon in a separate process, so we can continue doing stuff in
    # this one afterwards
    new_pid = os.fork()
    if new_pid == 0:
        # create new daemon context and run bootstrapper inside it
        with daemon.DaemonContext(
                working_directory=os.path.abspath(os.path.dirname(__file__)),
                umask=0x002,
                stderr=open(Path(config.get('PATH_ROOT'), config.get('PATH_LOGS'), "4cat.stderr"), "w+"),
                detach_process=True
        ) as context:
            import backend.bootstrap as bootstrap
            bootstrap.run(as_daemon=True, log_level=args.log_level)

        sys.exit(0)

    else:
        # wait a few seconds and see if PIDfile was created by the bootstrapper
        # and refers to a running process
        now = time.time()
        while time.time() < now + 60:
            if pidfile.is_file():
                break
            else:
                time.sleep(0.1)

        if not pidfile.is_file():
            print("...error while starting 4CAT Backend Daemon (pidfile not found).")
            return False

        else:
            with pidfile.open() as infile:
                pid = int(infile.read().strip())
                if pid in psutil.pids():
                    print("...4CAT Backend Daemon started.")
                else:
                    print("...error while starting 4CAT Backend Daemon (PID invalid).")

    return True


def stop(force=False):
    """
    Stop the backend daemon, if it is running

    Sends a SIGTERM signal - this is intercepted by the daemon after which it
    shuts down gracefully.

    :param bool force:  send SIGKILL if process does not quit quickly enough?

    :return bool:   True if the backend was running (and a shut down signal was
                    sent, False if not.
    """
    killed = False

    if pidfile.is_file():
        # see if the listed process is actually running right now
        with pidfile.open() as infile:
            pid = int(infile.read().strip())

        if pid not in psutil.pids():
            print("...error: 4CAT Backend Daemon is not running, but a PID file exists. Has it crashed?")
            return False

        # tell the backend to stop
        os.system("kill -15 %s" % str(pid))
        print("...sending SIGTERM to process %i. Waiting for backend to quit..." % pid)

        # periodically check if the process has quit
        starttime = time.time()
        while pid in psutil.pids():
            nowtime = time.time()
            if nowtime - starttime > 60:
                # give up if it takes too long
                if force == True and not killed:
                    os.system("kill -9 %s" % str(pid))
                    print("...error: the 4CAT backend daemon did not quit within 60 seconds. Sending SIGKILL...")
                    killed = True
                    starttime = time.time()
                else:
                    print(
                        "...error: the 4CAT backend daemon did not quit within 60 seconds. A worker may not have quit (yet).")
                    return False
            time.sleep(1)

        if killed and pidfile.is_file():
            # SIGKILL doesn't clean up the pidfile, so we do it here
            pidfile.unlink()

        print("...4CAT Backend stopped.")
        return True
    else:
        # no pid file, so nothing running
        print("...the 4CAT backend daemon is not currently running.")
        return True


# ---------------------------------------------
#   Show manual, if command does not exists
# ---------------------------------------------
manual = """Usage: python(3) backend.py <start|stop|restart|force-restart|force-stop|status>

Starts, stops or restarts the 4CAT backend daemon.
"""
if args.command not in ("start", "stop", "restart", "status", "force-restart", "force-stop"):
    print(manual)
    sys.exit(1)

# determine command given and get the current PID (if any)
command = args.command
if pidfile.is_file():
    with pidfile.open() as file:
        pid = int(file.read().strip())
else:
    pid = None

# ---------------------------------------------
#        Run code for valid commands
# ---------------------------------------------
if command in ("restart", "force-restart"):
    print("Restarting 4CAT Backend Daemon...")
    # restart daemon, but only if it's already running and could successfully be stopped
    stopped = stop(force=(command == "force-restart"))
    if stopped:
        print("...starting 4CAT Backend Daemon...")
        start()
elif command == "start":
    # start...but only if there currently is no running backend process
    print("Starting 4CAT Backend Daemon...")
    start()
elif command in ("stop", "force-stop"):
    # stop
    print("Stopping 4CAT Backend Daemon...")
    sys.exit(0 if stop(force=(command == "force-stop")) else 1)
elif command == "status":
    # show whether the daemon is currently running
    if not pid:
        print("4CAT Backend Daemon is currently not running.")
    elif pid in psutil.pids():
        print("4CAT Backend Daemon is currently up and running.")

        # fetch more detailed status via internal API
        if not config.get('API_PORT'):
            sys.exit(0)

        print("\n     Active workers:\n-------------------------")
        active_workers = call_api("workers")["response"]
        active_workers = {worker: active_workers[worker] for worker in
                          sorted(active_workers, key=lambda id: active_workers[id], reverse=True) if
                          active_workers[worker] > 0}
        for worker in active_workers:
            print("%s: %i" % (worker, active_workers[worker]))

        print("\n")


    else:
        print("4CAT Backend Daemon is not running, but a PID file exists. Has it crashed?")
