import requests
import time
import config
import csv
from lib.database import Database
from lib.logger import Logger
from lib.worker import BasicWorker
from bs4 import BeautifulSoup

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
        self.allowed_cols = ['post_vector', 'body_vector', 'title_vector']

    def work(self):

        job = self.queue.get_job("query")

        if not job:
            self.log.info("No string queries")
            # for debugging:
            # self.queue.add_job(type="query", details={"str_query": "skyrim", "col_query": "body_vector"})
            time.sleep(10)

        else:

            try:
                self.queue.claim_job(job)
            except JobClaimedException:
                return JobClaimedException

            self.log.info("Executing string query")

            col = job["details"]["col_query"]
            query = job["details"]["str_query"]

            if col not in self.allowed_cols:
                self.log.warning("Column %s is not allowed. Use post_vector, body_vector, or title_vector" % (col))

            # execute the query on the relevant column
            result = self.executeQuery(str(col), str(query))

            #convert and write to csv
            result = self.dictToCsv(result, 'mentions_' + query)

            if result == 'invalid_column':
                self.queue.finish_job(job)
            else:
                # done!
                self.queue.finish_job(job)

        looping = False

    def executeQuery(self, col_query, str_query):
        """
        Query the relevant column
        To do: create csv out of data and store in a 'data' folder (put location in config)
        """
        self.log.info('Starting fetching ' + col_query + ' containing \'' + str_query + '\'')

        start_time = time.time()
        try:
            if col_query == 'body_vector':
                string_matches = self.db.fetchall("SELECT id, timestamp, subject, body FROM posts WHERE body_vector @@ to_tsquery(%s);", (str_query,))
            elif col_query == 'subject_vector':
                string_matches = self.db.fetchall("SELECT id, timestamp, subject, body FROM posts WHERE subject_vector @@ to_tsquery(%s);", (str_query,))
            else:
                return 'invalid_column'
        except Exception as error:
           return str(error)
        self.log.info('Finished fetching ' + col_query + ' containing \'' + str_query + '\' in ' + str(round((time.time() - start_time), 4)) + ' seconds')

        return string_matches

    def dictToCsv(self, input_di, filename='', clean_csv=False):
        """
        Takes a dictionary of results, converts it to a csv, and writes it to the data folder.
        The respective csvs will be available to the user.
        """
        self.log.info(type(input_di))
        # some error handling
        if type(input_di) != list:
            self.log.error('Please use a list object to convert to csv')
            return -1
        if filename == '':
            self.log.error('Please insert a filename for the csv')
            return -1

        data_dir = config.PATH_DATA +  filename + '.csv'
        fieldnames = ['id', 'timestamp', 'body', 'subject']
        
        # write the dictionary to a csv
        with open(data_dir, 'w', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, lineterminator = '\n')
            writer.writeheader()

            if clean_csv:
                for post in input_di:
                    # Parsing: remove the HTML tags, but keep the <br> as a newline
                    post['body'] = post['body'].replace('<br>', '\n')
                    post["body"] = BeautifulSoup(post["body"], 'html.parser').get_text()
                    writer.writerow(post)
            else:
                writer.writerows(input_di)

        return data_dir