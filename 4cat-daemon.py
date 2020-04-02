import time
import sys
import os

from pathlib import Path

import config
import backend.bootstrap as bootstrap

from backend.lib.helpers import call_api

# check validity of config file
# (right now, just check if defaults have been updated where required)
if not config.ANONYMISATION_SALT or config.ANONYMISATION_SALT == "REPLACE_THIS":
	print("You need to set a random value for anonymisation in config.py before you can run 4CAT. Look for the ANONYMISATION_SALT option.")
	sys.exit(1)

# check if we can run a daemon
if os.name not in ("posix"):
	# if not, run the backend directly and quit
	print("Using '%s' to run the 4CAT backend is only supported on UNIX-like systems." % __file__)
	print("Running backend in terminal instead.")
	bootstrap.run(as_daemon=False)
	sys.exit(0)


if sys.argv[-2].lower() in ("-i", "--interactive"):
	print("Running backend in interactive mode.")
	bootstrap.run(as_daemon=False)
	sys.exit(0)
else:
	# if so, import necessary modules
	import psutil
	import daemon
	from daemon import pidfile

# determine PID file
lockfile = Path(config.PATH_ROOT, config.PATH_LOCKFILE, "4cat.pid") # pid file location


def start():
	"""
	Start backend, as a daemon
	:return bool: True
	"""
	# only one instance may be running at a time
	if lockfile.is_file():
		with lockfile.open() as file:
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
				pidfile=pidfile.TimeoutPIDLockFile(str(lockfile)),
				detach_process=True
		) as context:
			bootstrap.run(as_daemon=True)
		sys.exit(0)
	else:
		# wait a few seconds and see if PIDfile was created and refers to a running process
		now = time.time()
		while time.time() < now + 10:
			if lockfile.is_file():
				break
			else:
				time.sleep(0.1)

		if not lockfile.is_file():
			print("...error while starting 4CAT Backend Daemon (lockfile not found).")
		else:
			with lockfile.open() as file:
				pid = int(file.read().strip())
				if pid in psutil.pids():
					print("...4CAT Backend Daemon started.")
				else:
					print("...error while starting 4CAT Backend Daemon.")

		if Path("4cat.stderr").is_file():
			with open("4cat.stderr") as errfile:
				stderr = errfile.read()
				if stderr:
					print("---------------------------------\nstderr output:")
					print(stderr)

	return True


def stop(signal=15):
	"""
	Stop the backend daemon, if it is running

	Sends a SIGTERM signal - this is intercepted by the daemon after which it
	shuts down gracefully.

	:param int signal:  Kill signal, defaults to 15/SIGTERM

	:return bool:   True if the backend was running (and a shut down signal was
					sent, False if not.

	"""
	if lockfile.is_file():
		# see if the listed process is actually running right now
		with lockfile.open() as file:
			pid = int(file.read().strip())

		if pid not in psutil.pids():
			print("...error: 4CAT Backend Daemon is not running, but a PID file exists. Has it crashed?")
			return False

		# tell the backend to stop
		signame = {9: "SIGKILL", 15: "SIGTERM"}.get(signal, "-%s" % str(signal))
		os.system("kill -%s %s" % (str(signal), str(pid)))
		print("...sending %s to process %i. Waiting for backend to quit..." % (signame, pid))

		# periodically check if the process has quit
		starttime = time.time()
		while pid in psutil.pids():
			nowtime = time.time()
			if nowtime - starttime > 60:
				# give up if it takes too long
				print("...error: the 4CAT backend daemon did not quit within 60 seconds. Something probably crashed.")
				return False
			time.sleep(1)

		if signal == 9 and lockfile.is_file():
			# SIGKILL doesn't clean up the pidfile, so we do it here
			os.unlink(lockfile)

		print("...4CAT Backend stopped.")
		return True
	else:
		# no pid file, so nothing running
		print("...error: the 4CAT backend daemon is not currently running.")
		return False


# display manual if invalid command was given
manual = """Usage: python(3) backend.py <start|stop|restart|force-restart|status>

Starts, stops or restarts the 4CAT backend daemon.
"""
if len(sys.argv) < 2 or sys.argv[1].lower() not in ("start", "stop", "restart", "status", "force-restart"):
	print(manual)
	sys.exit(1)

# determine command given and get the current PID (if any)
command = sys.argv[-1].lower()
if lockfile.is_file():
	with lockfile.open() as file:
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
elif command == "force-restart":
	# force quit and start
	print("Force-restarting 4CAT Backend Daemon...")
	# restart daemon, but only if it's already running and could successfully be stopped
	stopped = stop(9)
	if stopped:
		print("...starting 4CAT Backend Daemon...")
		start()
elif command == "status":
	# show whether the daemon is currently running
	if not pid:
		print("4CAT Backend Daemon is currently not running.")
	else:
		if pid in psutil.pids():
			print("4CAT Backend Daemon is currently up and running.")

			# fetch more detailed status via internal API
			if not config.API_PORT:
				sys.exit(0)

			print("\n     Active workers:\n-------------------------")
			active_workers = call_api("workers")["response"]
			active_workers = {worker: active_workers[worker] for worker in sorted(active_workers, key=lambda id: active_workers[id], reverse=True) if active_workers[worker] > 0}
			for worker in active_workers:
				print("%s: %i" % (worker, active_workers[worker]))

			print("\n")


		else:
			print("4CAT Backend Daemon is not running, but a PID file exists. Has it crashed?")
