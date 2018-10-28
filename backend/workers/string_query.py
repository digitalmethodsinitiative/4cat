import time
import config
import csv
import os
import pickle as p

from backend.lib.database import Database
from backend.lib.logger import Logger
from backend.lib.query import SearchQuery
from backend.lib.queue import JobClaimedException
from backend.lib.helpers import get_absolute_folder
from backend.lib.worker import BasicWorker

from bs4 import BeautifulSoup


class stringQuery(BasicWorker):
	"""
	Process substring queries from the front-end
	Requests are added to the pool as "query" jobs

	"""

	type = "query"
	pause = 2
	max_workers = 3

	# Columns to return in csv.
	# Mandatory columns:
	# ['thread_id', 'body', 'subject', 'timestamp']
	li_return_cols = ['thread_id', 'id', 'timestamp', 'body', 'subject']

	def __init__(self, logger, manager):
		"""
		Set up database connection - we need one to perform the query
		"""
		super().__init__(logger=logger, manager=manager)

	def work(self):

		job = self.queue.get_job(jobtype="query")

		if not job:
			self.log.debug("No string queries, sleeping for 10 seconds")
			time.sleep(10)

		else:
			try:
				self.queue.claim_job(job)
			except JobClaimedException:
				return

			# Setup connections and get parameters
			log = Logger()
			db = Database(logger=log)
			key = job["remote_id"]
			query = SearchQuery(key=key, db=db)
			query_parameters = query.get_parameters()
			results_dir = query.get_results_dir()
			results_file = query.get_results_path() 

			# If keyword-dense threads are selected, get and write matching threads first,
			# and set the "dense_threads" parameters as this list
			if query_parameters["dense_threads"]:
				matching_threads = self.get_dense_threads(query_parameters)
				self.dict_to_csv(matching_threads, results_dir + '/metadata_dense_threads_' + query_parameters["body_query"] + ".csv", clean_csv=False)
				if matching_threads:
					li_thread_ids = tuple([thread["thread_id"] for thread in matching_threads])
					query_parameters["dense_threads"] = li_thread_ids
				else:
					# No keyword-dense thread results
					query.set_empty()
					query.finish()
					self.queue.finish_job(job)
					return -1
			
			# Get posts
			self.log.info("Executing substring query")
			di_matches = self.execute_string_query(query_parameters)
			
			# Write to csv if there substring matches. Else set query as empty.
			if di_matches:
				self.dict_to_csv(di_matches, results_file)
			else:
				query.set_empty()

			# Done!
			query.finish()
			self.queue.finish_job(job)

		looping = False

	def execute_string_query(self, query_parameters):
		"""
		Query the relevant column of the chan data.
		Converts parameters to SQL statements.
		Returns the results in a dictionary.

		:param query_parameters		dict, dictionary of query job parameters
		
		"""
		
		body_query = query_parameters["body_query"]
		subject_query = query_parameters["subject_query"]
		full_thread = query_parameters["full_thread"]
		dense_threads = query_parameters["dense_threads"]
		dense_percentage = query_parameters["dense_percentage"]
		dense_length = query_parameters["dense_length"]
		min_date = query_parameters["min_date"]
		max_date = query_parameters["max_date"]

		# Set SQL statements depending on job parameters
		replacements = []
		sql_post = ''
		sql_subject = ''
		sql_min_date = ''
		sql_max_date = ''
		sql_columns = ', '.join(self.li_return_cols)
		sql_log = 'Starting substring query where '

		# Generate SQL query string
		if body_query != 'empty':
			sql_post = " AND body_vector @@ plainto_tsquery('" + body_query + "')"
			replacements.append(sql_post)
			sql_log = sql_log + "'" + body_query + "' is in body, "
		if subject_query != 'empty':
			sql_subject = " AND subject_vector @@ plainto_tsquery('" + subject_query + "')"
			replacements.append(sql_subject)
			sql_log = sql_log + "'" + subject_query + "' is in subject, "
		if min_date != 0:
			sql_min_date = " AND timestamp > " + str(min_date)
			replacements.append(sql_min_date)
			sql_log = sql_log + "is posted after " + str(min_date) + ", "
		if max_date != 0:
			sql_max_date = " AND timestamp < " + str(max_date)
			replacements.append(sql_max_date)
			sql_log = sql_log + "is posted before " + str(max_date) + ", "

		# Start some timekeeping
		start_time = time.time()

		# Fetch only posts
		if dense_threads is False and full_thread is False:

			# Log SQL query
			sql_log = sql_log[:-2] + '.'
			self.log.info(sql_log)
			self.log.info("SELECT " + sql_columns + " FROM posts WHERE true" + ' '.join(replacements))

			try:
				di_matches = self.db.fetchall("SELECT " + sql_columns + " FROM posts WHERE true" + sql_post + sql_subject + sql_min_date + sql_max_date, replacements)
			except Exception as error:
				return str(error)

		# Fetch full thread data
		elif dense_threads != False or (full_thread and subject_query != 'empty'):

			# Get the IDs of the matching threads
			li_thread_ids = []
			if dense_threads != False:
				li_thread_ids = dense_threads
			else:
				try:
					li_thread_ids = self.db.fetchall("SELECT thread_id FROM posts WHERE true" + sql_post + sql_subject + sql_min_date + sql_max_date, replacements)
				except Exception as error:
					return str(error)
				# Convert matching OP ids to tuple
				li_thread_ids = tuple([thread["thread_id"] for thread in li_thread_ids])

			# Fetch posts within matching thread IDs
			try:
				di_matches = self.db.fetchall("SELECT " + sql_columns + " FROM posts WHERE thread_id IN %s ORDER BY thread_id, timestamp", (li_thread_ids,))
			except Exception as error:
				return str(error)
		
		else:
			self.log.warning("Not enough parameters provided for substring query.")
			return -1

		self.log.info("Finished query in " + str(round((time.time() - start_time), 4)) + " seconds")
		return di_matches

	def get_dense_threads(self, parameters):
		"""
		Get metadata from keyword-dense threads

		"""
		
		# Get relevant parameter values
		body_query = parameters["body_query"]
		dense_length = parameters["dense_length"]
		dense_percentage = parameters["dense_percentage"]

		self.log.info("Getting keyword-dense threads for " + body_query + " with a minimum thread length of " + str(dense_length) + " and a keyword density of " + str(dense_percentage) + ".")

		matching_threads = self.db.fetchall("""
			SELECT thread_id, num_replies, keyword_count, keyword_density FROM (
				SELECT thread_id, num_replies, keyword_count, ((keyword_count::real / num_replies::real) * 100) AS keyword_density FROM (
					SELECT posts.thread_id, threads.num_replies, count(*) as keyword_count FROM posts
					INNER JOIN threads ON posts.thread_id = threads.id
					WHERE posts.body_vector @@ to_tsquery(%s)
					AND posts.thread_id = threads.id
					GROUP BY posts.thread_id, threads.num_replies
				) AS thread_matches
			) AS thread_meta
			WHERE num_replies >= %s
			AND keyword_density >= %s

			"""
			, (body_query, dense_length, dense_percentage,))

		# Convert threads to tuple
		self.log.info("Found " + str(len(matching_threads)) + " " + body_query + "-dense threads.")

		return matching_threads

	def dict_to_csv(self, sql_results, filepath, clean_csv=True):
		"""
		Takes a dictionary of results, converts it to a csv, and writes it to the data folder.
		The respective csvs will be available to the user.

		:param sql_results:		list with results derived with db.fetchall()
		:param filepath:    	filepath for the resulting csv
		:param clean_csv:   	whether to parse the raw HTML data to clean text.
								If True (default), writing takes 1.5 times longer.

		"""

		# some error handling
		if type(sql_results) != list:
			self.log.error('Please use a dict object instead of ' +  str(type(sql_results)) + ' to convert to csv')
			return -1
		if filepath == '':
			self.log.error('No file path for results file provided')
			return -1

		#sql_results = sql_results[0]
		fieldnames = list(sql_results[0].keys())

		# write the dictionary to a csv
		with open(filepath, 'w', encoding='utf-8') as csvfile:
			writer = csv.DictWriter(csvfile, fieldnames=fieldnames, lineterminator='\n')
			writer.writeheader()

			if clean_csv:
				# Parsing: remove the HTML tags, but keep the <br> as a newline
				# Takes around 1.5 times longer
				for row in sql_results:
					row["body"] = row["body"].replace("<br>", "\n")
					row["body"] = BeautifulSoup(row["body"], "html.parser").get_text()
					writer.writerow(row)
			else:
				writer.writerows(sql_results)

		return filepath