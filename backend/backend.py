import daemon
import psutil
import time
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + '/..')
import config
import bootstrap

from lib.helpers import get_absolute_folder
from daemon import pidfile

lockfile = get_absolute_folder(config.PATH_LOCKFILE) + "/4cat.pid"  # pid file location


def start():
	"""
	Start backend, as a daemon
	:return bool: True
	"""
	print("Starting 4CAT Backend Daemon.")

	with daemon.DaemonContext(
			working_directory=os.path.abspath(os.path.dirname(__file__)),
			umask=0x002,
			pidfile=pidfile.TimeoutPIDLockFile(lockfile)
	) as context:
		bootstrap.run()

	return True


def stop():
	"""
	Stop the backend daemon, if it is running

	Sends a SIGTERM signal - this is intercepted by the daemon after which it
	shuts down gracefully.

	:return bool:   True if the backend was running (and a shut down signal was
					sent, False if not.
	"""
	if os.path.isfile(lockfile):
		with open(lockfile) as file:
			pid = int(file.read().strip())

		if pid not in psutil.pids():
			print("...error: the 4CAT backend daemon is not currently running.")
			return False

		os.system("kill %s" % str(pid))
		print("Sending SIGTERM to process %i. Waiting for backend to quit..." % pid)
		starttime = time.time()
		while pid in psutil.pids():
			nowtime = time.time()
			if nowtime - starttime > 60:
				print("...error: the 4CAT backend daemon did not quit within 60 seconds. Something probably crashed.")
				return False
			time.sleep(1)
		print("4CAT Backend stopped.")
		return True
	else:
		print("...error: the 4CAT backend daemon is not currently running.")
		return False


manual = """Usage: python(3) backend.py <start|stop|restart|status>

Starts, stops or restarts the 4CAT backend daemon.
"""
if len(sys.argv) < 2 or sys.argv[1].lower() not in ("start", "stop", "restart", "status"):
	print(manual)
	sys.exit(1)

# determine command given and get the current PID (if any)
command = sys.argv[1].lower()
if os.path.isfile(lockfile):
	with open(lockfile) as file:
		pid = int(file.read().strip())
else:
	pid = None

# interpret commands
if command == "restart":
	# restart daemon, but only if it's already running and could successfully be stopped
	stopped = stop()
	if stopped:
		start()
elif command == "start":
	# start...but only if there currently is no running backend process
	if pid in psutil.pids():
		print("Already running.")
	else:
		start()
elif command == "stop":
	# stop
	stop()
elif command == "status":
	# show whether the daemon is currently running
	if not pid:
		print("4CAT Backend Daemon is currently not running.")
	else:
		if pid in psutil.pids():
			print("4CAT Backend Daemon is currently up and running.")
		else:
			print("4CAT Backend Daemon is not running, but a PID file exists. Has it crashed?")
