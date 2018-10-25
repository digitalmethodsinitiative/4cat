import psutil
import time
import sys
import os

import config
import backend.bootstrap as bootstrap

from backend.lib.helpers import get_absolute_folder

# check if we can run a daemon
if os.name not in ("posix", "mac"):
	# if not, run the backend directly and quit
	print("Using 'backend.py' to run the 4CAT backend is only supported on UNIX-like systems.")
	print("Running backend in terminal instead.")
	bootstrap.run(as_daemon=False)
	sys.exit(0)

# if so, import necessary modules
import daemon
from daemon import pidfile

# determine PID file
lockfile = get_absolute_folder(config.PATH_LOCKFILE) + "/4cat.pid"  # pid file location


def start():
	"""
	Start backend, as a daemon
	:return bool: True
	"""
	# only one instance may be running at a time
	if os.path.isfile(lockfile):
		with open(lockfile) as file:
			pid = int(file.read().strip())

		if pid in psutil.pids():
			print("...error: the 4CAT Backend Daemon is already running.")
			return False

	# start daemon in a separate process so we can continue doing stuff in this one afterwards
	new_pid = os.fork()
	if new_pid == 0:
		# create new daemon context and run bootstrapper inside it
		with daemon.DaemonContext(
				working_directory=os.path.abspath(os.path.dirname(__file__)),
				umask=0x002,
				stderr=open("4cat.stderr", "w"),
				pidfile=pidfile.TimeoutPIDLockFile(lockfile),
				detach_process=True
		) as context:
			bootstrap.run(as_daemon=False)
		sys.exit(0)
	else:
		# wait a few seconds and see if PIDfile was created and refers to a running process
		time.sleep(3)
		if not os.path.isfile(lockfile):
			print("...error while starting 4CAT Backend Daemon.")
		else:
			with open(lockfile) as file:
				pid = int(file.read().strip())
				if pid in psutil.pids():
					print("...4CAT Backend Daemon started.")
				else:
					print("...error while starting 4CAT Backend Daemon.")

		if os.path.isfile("4cat.stderr"):
			with open("4cat.stderr") as errfile:
				stderr = errfile.read()
				if stderr:
					print("---------------------------------\nstderr output:")
					print(stderr)

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
		# see if the listed process is actually running right now
		with open(lockfile) as file:
			pid = int(file.read().strip())

		if pid not in psutil.pids():
			print("...error: 4CAT Backend Daemon is not running, but a PID file exists. Has it crashed?")
			return False

		# tell the backend to stop
		os.system("kill %s" % str(pid))
		print("...sending SIGTERM to process %i. Waiting for backend to quit..." % pid)

		# periodically check if the process has quit
		starttime = time.time()
		while pid in psutil.pids():
			nowtime = time.time()
			if nowtime - starttime > 60:
				# give up if it takes too long
				print("...error: the 4CAT backend daemon did not quit within 60 seconds. Something probably crashed.")
				return False
			time.sleep(1)

		# backend quit gracefully
		print("...4CAT Backend stopped.")
		return True
	else:
		# no pid file, so nothing running
		print("...error: the 4CAT backend daemon is not currently running.")
		return False


# display manual if invalid command was given
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
	print("Restarting 4CAT Backend Daemon...")
	# restart daemon, but only if it's already running and could successfully be stopped
	stopped = stop()
	if stopped:
		print("...starting 4CAT Backend Daemon...")
		start()
elif command == "start":
	# start...but only if there currently is no running backend process
	print("Starting 4CAT Backend Daemon...")
	start()
elif command == "stop":
	# stop
	print("Stopping 4CAT Backend Daemon...")
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
