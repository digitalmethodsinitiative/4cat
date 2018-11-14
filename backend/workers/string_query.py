import time
import config
import csv
import os
import pickle as p
import re
import mysql

from bs4 import BeautifulSoup
from datetime import datetime

from backend.lib.database import Database
from backend.lib.logger import Logger
from backend.lib.query import SearchQuery
from backend.lib.queue import JobClaimedException
from backend.lib.helpers import get_absolute_folder
from backend.lib.worker import BasicWorker

class stringQuery(BasicWorker):
	"""
	Process substring queries from the front-end
	Requests are added to the pool as "query" jobs

	"""

	type = "query"
	pause = 2
	max_workers = 3

	# Columns to return in csv
	# Mandatory columns: ['thread_id', 'body', 'subject', 'timestamp']
	li_return_cols = ['thread_id', 'id', 'timestamp', 'body', 'subject', 'author', 'image_file', 'image_md5', 'country_name']

	def __init__(self, logger, manager):
		"""
		Set up database connection - we need one to perform the query

		"""
		super().__init__(logger=logger, manager=manager)

		# Connect to the Sphinx database
		sphinx_db = mysql.connector.connect(
			host = "localhost",
			user = config.DB_USER,
			passwd = config.DB_PASSWORD,
			port = 9306
		)

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
			results_file = results_file.replace("*","")

			# If keyword-dense threads are selected, get and write matching threads first,
			# and set the "dense_threads" parameters as this list
			if query_parameters["dense_threads"]:
				matching_threads = self.get_dense_threads(query_parameters)

				if matching_threads:
					self.psql_results_to_csv(matching_threads, results_dir + '/metadata_dense_threads_' + query_parameters["body_query"].replace("*", "") + ".csv", clean_csv=False)
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
			li_matches = self.execute_string_query(query_parameters)
			
			# Write to csv if there substring matches. Else set query as empty.
			if li_matches:
				self.psql_results_to_csv(li_matches, results_file)
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
		
		# Connect to the Sphinx database
		sphinx_cursor =  self.sphinx_db.cursor()

		board = query_parameters["board"]
		body_query = query_parameters["body_query"]
		subject_query = query_parameters["subject_query"]
		full_thread = query_parameters["full_thread"]
		dense_threads = query_parameters["dense_threads"]
		dense_percentage = query_parameters["dense_percentage"]
		dense_length = query_parameters["dense_length"]
		min_date = query_parameters["min_date"]
		max_date = query_parameters["max_date"]

		# Check if there's anything in quotation marks for LIKE operations
		pattern = "\*(.*?)\*"
		li_exact_body = re.findall(pattern, body_query)
		li_exact_subject = re.findall(pattern, subject_query)
		body_query = body_query.replace("*", "")
		subject_query = subject_query.replace("*", "")

		# Set SQL statements depending on job parameters
		replacements = []
		sql_board = ''
		sql_text = ''
		sql_min_date = ''
		sql_max_date = ''
		sql_columns = ', '.join(self.li_return_cols)
		sql_log = 'Starting substring query where '
		
		sql_log = sql_log + "posts are on " + board + ", "
		
		# Generate query string MATCH() with Sphinx
		if body_query != "empty" or subject_query != "empty":
			sql_text = " AND MATCH('"
			if body_query != "empty":
				# Sphinx search
				sql_text = sql_text + " @body " + body_query
				sql_log = sql_log + "'" + body_query + "' is in body, "
				# If there are exact string matches between "quotation marks", loop through all entries and add
				if li_exact_body:
					for exact_body in li_exact_body:
						sql_text = sql_text + " @body \"" + exact_body + "\""
						sql_log = sql_log + "body exactly matches '" + exact_body + "', "
				replacements.append(sql_text)
			
			if subject_query != 'empty':
				sql_text = sql_text + " @subject " + subject_query
				sql_log = sql_log + "'" + subject_query + "' is in subject, "
				# If there are exact string matches between "quotation marks", loop through all entries and add
				if li_exact_subject:
					for exact_subject in li_exact_subject:
						sql_text = sql_text + " @subject \"" + exact_subject + "\""
						sql_log = sql_log + "subject exactly matches '" + exact_subject + "', "
				replacements.append(sql_text)
			sql_text = sql_text + "')"

		if min_date != 0:
			sql_min_date = " AND timestamp >= " + str(min_date)
			replacements.append(sql_min_date)
			sql_log = sql_log + "is posted after " + str(min_date) + ", "
		if max_date != 0:
			sql_max_date = " AND timestamp <= " + str(max_date)
			replacements.append(sql_max_date)
			sql_log = sql_log + "is posted before " + str(max_date) + ", "
		sql_log = sql_log[:-2] + '.'

		# Start some timekeeping
		start_time = time.time()

		# Fetch only posts
		if dense_threads is False and full_thread is False:

			# Log SQL query
			self.log.info(sql_log)
			self.log.info('First fetching matching post ids')
			self.log.info("SELECT post_id FROM 4cat_posts WHERE true AND " + sql_text + sql_min_date + sql_max_date)

			# Get the post ids for all posts that match the sphinx query
			try:
				li_matches = sphinx_cursor.fetchall("SELECT post_id FROM 4cat_posts WHERE true" + sql_board + sql_text + sql_min_date + sql_max_date)
			except Exception as error:
				return str(error)

			# Convert matching ids to tuple
			li_ids = tuple([post["post_id"] for post in li_matches])

			# If there are no posts matching the string query, return an empty list
			if len(li_ids) == 0:
				return li_ids

			# Now fetch the real posts with the ids
			self.log.info("Fetching posts that match the query")
			try:
				li_matches = self.db.fetchall("SELECT " + sql_columns + " FROM posts WHERE id IN %s ORDER BY thread_id, timestamp", (li_ids,))
			except Exception as error:
				return str(error)

			return li_matches

		# Fetch full thread data
		elif dense_threads != False or (full_thread and subject_query != 'empty'):
			
			# Log SQL query
			self.log.info("Getting full thread data, but first: " + sql_log)
			self.log.info("SELECT post_id FROM 4cat_posts WHERE true AND " + sql_text + sql_min_date + sql_max_date)

			# Get the IDs of the matching posts
			li_thread_ids = []

			# If this function is used for dense threads, skip the thread_id lookup
			if dense_threads != False:
				li_thread_ids = dense_threads
			else:

				# First, get the post ids (Sphinx table doesn't have thread_ids)
				try:
					li_matches = sphinx_cursor.fetchall("SELECT post_id FROM 4cat_posts WHERE true" + sql_text + sql_min_date + sql_max_date)
				except Exception as error:
					return str(error)
				
				# Convert matching ids to tuple
				li_ids = tuple([post["post_id"] for post in li_matches])

				# With the post ids, thread ids from the 'regular' posts table
				try:
					li_thread_ids = self.db.fetchall("SELECT thread_id FROM posts WHERE id in %s ", (li_ids,))
				except Exception as error:
					return str(error)
				
				# Convert matching thread_ids to tuple
				li_thread_ids = tuple([thread["thread_id"] for thread in li_thread_ids])

				# If there are no threads with the requested string in the title, return the empty list
				if len(li_thread_ids) == 0:
					return li_thread_ids
			
			# Fetch all posts with matching thread_ids
			try:
				li_matches = self.db.fetchall("SELECT " + sql_columns + " FROM posts WHERE thread_id IN %s ORDER BY thread_id, timestamp", (li_thread_ids,))
			except Exception as error:
				return str(error)
		
		else:
			self.log.warning("Not enough parameters provided for substring query.")
			return -1

		self.log.info("Finished query in " + str(round((time.time() - start_time), 4)) + " seconds")
		return li_matches

	def get_dense_threads(self, parameters):
		"""
		Get metadata from keyword-dense threads.
		Returns a list of thread IDs that match the keyboard-density parameters

		"""

		# Connect to the Sphinx database
		sphinx_cursor =  self.sphinx_db.cursor()
				
		# Get relevant parameter values
		board = parameters["board"]
		body_query = parameters["body_query"]
		dense_length = parameters["dense_length"]
		dense_percentage = parameters["dense_percentage"]
		min_date = parameters["min_date"]
		max_date = parameters["max_date"]

		# Set body query. Check if there's anything in quotation marks for LIKE operations.
		pattern = "\"(.*?)\""
		li_exact_body = re.findall(pattern, body_query)
		sql_body = " AND MATCH('@body " + body_query
		if li_exact_body:
			for exact_body in li_exact_body:
				sql_body = sql_body + " @body \"" + exact_body + "\""
		sql_body = sql_body + "')"

		body_query = body_query.replace("\"", "")
		
		# Indicate which boards to query
		sql_board = ''

		# Set timestamp parameters. Currently checks timestamp of all posts with keyword within paramaters.
		# Should perhaps change to OP timestamp.
		sql_min_date = ''
		sql_max_date = ''
		if min_date != 0:
			sql_min_date = " AND posts.timestamp >= " + str(min_date)
		if max_date != 0:
			sql_max_date = " AND posts.timestamp <= " + str(max_date)

		# First, get all the posts that match the string query with Sphinx
		self.log.info("Fetching ids from posts matching " + body_query)
		try:
			li_ids = sphinx_cursor.fetchall("SELECT post_id FROM 4cat_posts WHERE true" + sql_text + sql_min_date + sql_max_date)
		except Exception as error:
			return str(error)

		# Convert matching ids to tuple
		li_ids = tuple([post["post_id"] for post in li_matches])

		# With the post ids, get all the thread ids and metadata for the dense threads
		self.log.info("Getting keyword-dense threads on " + board + " for " + body_query + " with a minimum thread length of " + str(dense_length) + " and a keyword density of " + str(dense_percentage) + ".")		
		try:
			matching_threads = self.db.fetchall("""
				SELECT thread_id, num_replies, keyword_count, keyword_density::real FROM (
					SELECT thread_id, num_replies, keyword_count, ((keyword_count::real / num_replies::real) * 100) AS keyword_density FROM (
						SELECT posts.thread_id, threads.num_replies, count(*) as keyword_count FROM posts
						INNER JOIN threads ON posts.thread_id = threads.id
						WHERE posts.id IN(""" + li_ids + """)
						GROUP BY posts.thread_id, threads.num_replies
					) AS thread_matches
				) AS thread_meta
				WHERE num_replies >= """ + str(dense_length) + """
				AND keyword_density >= """ + str(dense_percentage) + """

				""")
		except Exception as error:
			return str(error)

		# Convert threads to tuple
		self.log.info("Found " + str(len(matching_threads)) + " " + body_query + "-dense threads.")

		return matching_threads

	def psql_results_to_csv(self, sql_results, filepath, clean_csv=True):
		"""
		Takes a dictionary of results, converts it to a csv, and writes it to the data folder.
		The respective csvs will be available to the user.

		:param sql_results:		List with results derived with db.fetchall()
		:param filepath:    	Filepath for the resulting csv
		:param clean_csv:   	Whether to parse the raw HTML data to clean text.
								If True (default), writing takes 1.5 times longer.

		"""

		# Error handling
		if type(sql_results) != list:
			self.log.error('Please use a list instead of ' +  str(type(sql_results)) + ' to convert to csv')
			self.log.error(sql_results)
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

					# Create human dates from timestamp
					from datetime import datetime
					row["timestamp"] = datetime.utcfromtimestamp(row["timestamp"]).strftime('%Y-%m-%d %H:%M:%S')

					# Clean body column
					row["body"] = row["body"].replace("<br>", "\n")
					row["body"] = BeautifulSoup(row["body"], "html.parser").get_text()

					writer.writerow(row)
			else:
				writer.writerows(sql_results)

		return filepath