"""
4CAT Backend init - run this to start the backend!
"""
import shutil
import os

from backend.lib.queue import JobQueue
from backend.lib.database import Database
from backend.lib.manager import WorkerManager
from backend.lib.logger import Logger


def run(as_daemon=True):
	if not as_daemon:
		indent_spaces = round(shutil.get_terminal_size().columns / 2) - 33
		indent = "".join([" " for i in range(0, indent_spaces)]) if indent_spaces > 0 else ""
		print("\n\n")
		print(indent + "+---------------------------------------------------------------+")
		print(indent + "|                                                               |")
		print(indent + "|                           welcome to                          |")
		print(indent + "|                                                               |")
		print(indent + "|                  j88D   .o88b.  .d8b.  d888888b               |")
		print(indent + "|                 j8~88  d8P  Y8 d8' `8b `~~88~~'               |")
		print(indent + "|                j8' 88  8P      88ooo88    88                  |")
		print(indent + "|                V88888D 8b      88~~~88    88                  |")
		print(indent + "|                    88  Y8b  d8 88   88    88                  |")
		print(indent + "|                    VP   `Y88P' YP   YP    YP                  |")
		print(indent + "|                                                               |")
		print(indent + "|               4CAT: Capture and Analysis Toolkit              |")
		print(indent + "|                         4cat.oilab.nl                         |")
		print(indent + "|                                                               |")
		print(indent + "+---------------------------------------------------------------+")
		print(indent + "|                  press q + enter to shut down                 |")
		print(indent + "|                                                               |")
		print(indent + "| WARNING: Not running as a daemon.  Quitting this process will |")
		print(indent + "|                 shut down the backend as well.                |")
		print(indent + "+---------------------------------------------------------------+\n\n")

	# load everything
	log = Logger(output=not as_daemon)
	db = Database(logger=log)
	queue = JobQueue(logger=log, database=db)

	#dbpath = os.path.abspath(os.path.dirname(__file__) + "/database.sql")
	#with open(dbpath, "r") as content_file:
	#	log.info("Initializing database...")
	#	database_setup = content_file.read()
	#	db.execute(database_setup)
	#	log.info("Database tables and indexes present.")

	# clean up after ourselves
	db.commit()
	queue.release_all()

	# make it happen
	WorkerManager(logger=log, database=db, queue=queue, as_daemon=as_daemon)
	log.info("4CAT Backend shut down.")