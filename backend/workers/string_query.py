import time
import config
import csv
import os
import pickle as p

from backend.lib.queue import JobClaimedException
from backend.lib.helpers import get_absolute_folder
from backend.lib.worker import BasicWorker
from bs4 import BeautifulSoup


class stringQuery(BasicWorker):
	"""
	Process substring queries from the front-end
	Requests are added to the pool as "query" jobs

	E.g. queue.addJob(type="query", details={"str_query": "skyrim", "col_query": "body_vector"})
	"""

	type = "query"
	pause = 2
	max_workers = 3

	def __init__(self, logger, manager):
		"""
		Set up database connection - we need one to perform the query
		"""
		super().__init__(logger=logger, manager=manager)

		self.allowed_cols = ['body_vector', 'title_vector']

	def work(self):

		job = self.queue.get_job("query")

		if not job:
			self.log.debug("No string queries, sleeping for 10 seconds")
			time.sleep(10)

		else:

			try:
				self.queue.claim_job(job)
			except JobClaimedException:
				return

			self.log.info("Executing string query")

			col = job["details"]["col_query"]
			query = job["details"]["str_query"]
			
			if "min_date" in job["details"] and "max_date" in job["details"]:
				min_date = job["details"]["min_date"]
				min_date = job["details"]["max_date"]

			if col not in self.allowed_cols:
				self.log.warning("Column %s is not allowed. Use body_vector and/or title_vector" % (col))
				return

			# execute the query on the relevant column
			result = self.execute_query(str(col), str(query))

			# if query results are not empty, convert and write to csv
			
			if len(result) > 0:
				print('RESULT')
				result = self.dict_to_csv(result, 'mentions_' + query)
				self.write_file_status(query, 'finished')
			else:
				print('NO RESULT')
				self.write_file_status(query, 'empty_file')

			# done!
			self.queue.finish_job(job)

		looping = False

	def execute_query(self, col_query, str_query, min_date=None, max_date=None):
		"""
		Query the relevant column of the chan data

		:param col_query:   string of the column to query (body_vector, subject_vector)
		:param str_query:   string to query
	
		"""
		self.log.info('Starting fetching ' + col_query + ' containing \'' + str_query + '\'')

		start_time = time.time()
		try:
			if col_query == 'body_vector':
				if min_date is None and max_date is None:
					string_matches = self.db.fetchall(
						"SELECT id, timestamp, subject, body FROM posts WHERE body_vector @@ to_tsquery(%s);", (str_query,))
				else:
					string_matches = self.db.fetchall(
						"SELECT id, timestamp, subject, body FROM posts WHERE body_vector @@ to_tsquery(%s) AND timestamp > %s AND timestamp < %s;", (str_query, min_date, max_date))
			elif col_query == 'subject_vector':
				string_matches = self.db.fetchall(
					"SELECT id, timestamp, subject, body FROM posts WHERE subject_vector @@ to_tsquery(%s);",
					(str_query,))

		except Exception as error:
			return str(error)

		self.log.info('Finished fetching ' + col_query + ' containing \'' + str_query + '\' in ' + str(
			round((time.time() - start_time), 4)) + ' seconds')

		return string_matches

	def dict_to_csv(self, li_input, filename='', clean_csv=True):
		"""
		Takes a dictionary of results, converts it to a csv, and writes it to the data folder.
		The respective csvs will be available to the user.

		:param li_input:    list derived with db.fetchall(), used as input
		:param filename:    filename for the resulting csv
		:param clean_csv:   whether to parse the raw HTML data to clean text. If True (default), writing takes 1.5 times longer.

		"""
		#self.log.info(type(li_input))
		# some error handling
		if type(li_input) != list:
			self.log.error('Please use a list object to convert to csv')
			return -1
		if filename == '':
			self.log.error('Please insert a filename for the csv')
			return -1

		filepath = get_absolute_folder(config.PATH_DATA) + "/" + filename + '.csv'

		# fields to save in the offered csv (tweak later)
		fieldnames = ['id', 'timestamp', 'body', 'subject']

		# write the dictionary to a csv
		with open(filepath, 'w', encoding='utf-8') as csvfile:
			writer = csv.DictWriter(csvfile, fieldnames=fieldnames, lineterminator='\n')
			writer.writeheader()

			if clean_csv:
				# Parsing: remove the HTML tags, but keep the <br> as a newline
				# Takes around 1.5 times longer
				for post in li_input:
					post['body'] = post['body'].replace('<br>', '\n')
					post["body"] = BeautifulSoup(post["body"], 'html.parser').get_text()
					writer.writerow(post)
			else:
				writer.writerows(li_input)

		return filepath

	def write_file_status(self, query, status):
		"""
		store the status of a query in a dictionary.
		statuses can be "finished" or "empty_file"

		"""

		# load the di with file statuses if it exits. Else use an empty dict.
		path_file_status = get_absolute_folder(config.PATH_DATA + '/queries/di_queries.p')
		if os.path.isfile(path_file_status):
			di_file_status = p.load(open(path_file_status, 'rb'))
		else:
			di_file_status = {}

		di_file_status[query] = status

		p.dump(di_file_status, open(path_file_status, 'wb'))
		