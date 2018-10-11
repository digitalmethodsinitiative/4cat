"""
4CAT Backend init - run this to start the backend!
"""
import psutil
import sys
import os

from lib.queue import JobQueue
from lib.database import Database
from lib.manager import WorkerManager
from lib.logger import Logger

print("""
+---------------------------------------------------------------+
|                                                               |
|                           welcome to                          |
|                                                               |
|                  j88D   .o88b.  .d8b.  d888888b               |
|                 j8~88  d8P  Y8 d8' `8b `~~88~~'               |
|                j8' 88  8P      88ooo88    88                  |
|                V88888D 8b      88~~~88    88                  |
|                    88  Y8b  d8 88   88    88                  |
|                    VP   `Y88P' YP   YP    YP                  |
|                                                               |
|               4CAT: Capture and Analysis Toolkit              |
|                         4cat.oilab.eu                         |
|                                                               |
+---------------------------------------------------------------+    
""")

# init - check if a lockfile exists and if so, whether the PID in it is still active
lockfile = "4cat-backend.lock"
if os.path.isfile(lockfile):
    with open(lockfile) as pidfile:
        pid = pidfile.read().strip()
        if int(pid) in psutil.pids():
            print("Error: 4CAT Backend is already running (PID %s). Only one instance may be active at any time." % pid)
            sys.exit(1)

with open("4cat-backend.lock", "w") as pidfile:
    pidfile.write(str(os.getpid()))

# load everything
looping = True
log = Logger()
db = Database(logger=log)
queue = JobQueue(logger=log)

with open("database.sql", "r") as content_file:
    log.info("Initializing database...")
    #database_setup = content_file.read()
    #db.execute(database_setup)
    log.info("Database tables and indexes present.")

# clean up after ourselves
db.commit()
queue.release_all()

# make it happen
WorkerManager(logger=log)

print("ok")