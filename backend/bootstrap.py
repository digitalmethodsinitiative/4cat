"""
4CAT Backend init - used to start the backend!
"""
import shutil
import os

from pathlib import Path

from common.lib.queue import JobQueue
from common.lib.database import Database
from common.lib.module_loader import ModuleCollector
from backend.lib.manager import WorkerManager
from common.lib.logger import Logger
from common.config_manager import ConfigManager

def run(as_daemon=True, log_level="INFO"):
	# initialise configuration reader
	config = ConfigManager()

	pidfile = Path(config.get('PATH_ROOT'), config.get('PATH_LOCKFILE'), "4cat.pid")

	if as_daemon:
		with pidfile.open("w") as outfile:
			outfile.write(str(os.getpid()))

	else:
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
		print(indent + "|                                                               |")
		print(indent + "|                                                               |")
		print(indent + "+---------------------------------------------------------------+")
		print(indent + "|                   use ctrl + c to shut down                   |")
		print(indent + "|                                                               |")
		print(indent + "| WARNING: Not running as a daemon.  Quitting this process will |")
		print(indent + "|                 shut down the backend as well.                |")
		print(indent + "+---------------------------------------------------------------+\n\n")

	# load everything
	log_folder = config.get('PATH_ROOT').joinpath(config.get('PATH_LOGS'))
	if config.get("USING_DOCKER"):
		as_daemon = True
		# Rename log if Docker setup
		log = Logger(output=True, log_path=log_folder.joinpath("backend_4cat.log"), log_level=log_level)
	else:
		log = Logger(output=not as_daemon, log_path=log_folder.joinpath("backend_4cat.log"), log_level=log_level)

	log.info("4CAT Backend started, logger initialised")
	db = Database(logger=log, appname="main",
				  dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD, host=config.DB_HOST, port=config.DB_PORT)
	queue = JobQueue(logger=log, database=db)

	# clean up after ourselves
	db.commit()
	queue.release_all()

	# test memcache and clear upon backend restart
	if config.get("MEMCACHE_SERVER"):
		if config.memcache:
			log.debug("Memcache connection initialized - clearing")
			config.clear_cache()
		else:
			log.warning(f"Memcache server address configured, but connection could not be initialized at "
						f"{config.get('MEMCACHE_SERVER')}. Configuration cache inactive.")

	# ensure database consistency for settings table
	config.with_db(db)
	config.ensure_database()

	log.load_webhook(config)

	# load 4CAT modules and cache the results
	modules = ModuleCollector(config=config, write_cache=True)

	# make it happen
	# this is blocking until the back-end is shut down
	WorkerManager(logger=log, database=db, queue=queue, modules=modules, as_daemon=as_daemon)

	# clean up pidfile, if running as daemon
	if as_daemon:
		if pidfile.exists():
			pidfile.unlink()

	log.info("4CAT Backend shut down.")
