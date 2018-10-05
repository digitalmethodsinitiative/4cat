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
|                       www.oilab.eu/4cat                       |
|                                                               |
+---------------------------------------------------------------+    
""")

# init
looping = True
scraper_threads = []
log = Logger()
db = Database(logger=log)
queue = JobQueue(logger=log)

with open("database.sql", "r") as content_file:
    log.info("Initializing database...")
    database_setup = content_file.read()
    db.execute(database_setup)
    log.info("Database tables and indexes present.")

# clean up after ourselves
db.commit()
queue.releaseAll()

# make it happen
WorkerManager(logger=log)