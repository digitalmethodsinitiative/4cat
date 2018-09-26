import sys

from lib.queue import JobQueue
from lib.database import Database
from lib.manager import WorkerManager
from lib.logger import Logger

# init
looping = True
scraper_threads = []
db = Database()
queue = JobQueue()
log = Logger()

with open("database.sql", "r") as content_file:
    log.info("Initializing database...")
    database_setup = content_file.read()
    db.execute(database_setup)
    log.info("Database tables and indexed present.")

# clean up after ourselves
db.commit()
queue.releaseAll()

# make it happen
WorkerManager()
