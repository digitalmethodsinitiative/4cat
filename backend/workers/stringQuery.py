import requests
import time
from lib.database import Database
from lib.logger import Logger
from lib.worker import BasicWorker
import config

class stringQuery(BasicWorker):
    """
    Process substring queries from the front-end
    Requests are added to the pool as "query" jobs

    The "col_query" field in the job['details'] determines what fields to query
    body_vector:        only post body
    subject_vector:     only post subject
    post_vector:        full post, both body and title

    E.g. queue.addJob(type="query", details={"str_query": "skyrim", "col_query": "body_vector"})
    """

    type = "query"
    pause = 2
    max_workers = 3

    def __init__(self, logger):
        """
        Set up database connection - we need one to perform the query
        """
        super().__init__(logger)

        self.db = Database(logger=self.log)
        allowed_cols = ['post_vector', 'body_vector', 'title_vector']

    def work(self):
        job = self.queue.getJob("query")

        if not job:
            self.log.info("No string queries")
            # for debugging:
            # self.queue.addJob(type="query", details={"str_query": "skyrim", "col_query": "body_vector"})
            time.sleep(10)

        else:
            self.log.info("Executing string query")

            # the relevant column to be queried (post_vector, body_vector, or title_vector)
            col = job["details"]["col_query"]

            if col not in self.allowed_cols:
                self.log.warning("Column %s is not allowed. Use post_vector, body_vector, or title_vector" % (col))

            query = job["details"]["str_query"]

            # execute the query on the relevant column
            self.executeQuery(str(col), str(query))

            # done!
            self.queue.finishJob(job)
        looping = False

    def executeQuery(self, col_query, str_query):
        """
        Query the relevant column
        To do: create csv out of data and store in a 'data' folder (put location in config)
        """
        db = Database(logger=Logger())
        start_time = time.time()
        string_matches = self.db.fetchall("SELECT id, body FROM posts WHERE %s @@ to_tsquery(%s);", (col_query, str_query))

        print('Finished fetching ' + col_query + ' containing \'' + str_query + '\' in ' + str(round((time.time() - start_time), 4)) + ' seconds')

        return string_matches
