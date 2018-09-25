from lib.queue import JobQueue
from lib.database import Database
from lib.manager import ScraperManager

# init
looping = True
scraper_threads = []
db = Database()
queue = JobQueue()

# clean up after ourselves
db.commit()
queue.releaseAll()

# make sure we have something to scrape
if queue.getJobCount() == 0:
    queue.addJob("board", None)

# make it happen
ScraperManager()
