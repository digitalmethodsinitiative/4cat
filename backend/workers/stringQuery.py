import requests
import time

from lib.worker import BasicWorker
import config

class stringQuery(BasicWorker):
    type = "query"
    pause = 2
    max_workers = 3

    def work(self):
        job = self.queue.getJob("query")
        if not job:
            self.log.info("No string queries")
            time.sleep(10)
        else:
            self.log.info("Executing string query")
            # not finished!
            # executeQuery()
        looping = False

    def executeQuery():
        string_matches = self.db.fetchall("SELECT * FROM threads WHERE comment LIKE  = %s", ()) # read up on postgres FTS
        # return string_matches