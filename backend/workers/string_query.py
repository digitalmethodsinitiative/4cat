import time
import csv

from pymysql import OperationalError
from bs4 import BeautifulSoup

import config
from backend.lib.database_mysql import MySQLDatabase
from backend.lib.query import SearchQuery
from backend.lib.queue import JobClaimedException
from backend.lib.worker import BasicWorker


class StringQuery(BasicWorker):
	"""
	Process substring queries from the front-end
	Requests are added to the pool as "query" jobs
	"""

	type = "query"
	pause = 2
	max_workers = 3

	sphinx = None
	query = None

	# Columns to return in csv
	# Mandatory columns: ['thread_id', 'body', 'subject', 'timestamp']
	return_cols = ['thread_id', 'id', 'timestamp', 'body', 'subject', 'author', 'image_file', 'image_md5',
				   'country_name']

	def work(self):
		"""
		Run 4CAT search query

		Gets query details, passes them on to the object's search method, and
		writes the results to a CSV file. If that all went well, the query and
		job are marked as finished.
		"""
		job = self.queue.get_job(jobtype="query")

		if not job:
			self.log.debug("No string queries, sleeping for 10 seconds")
			time.sleep(10)
			return

		try:
			self.queue.claim_job(job)
		except JobClaimedException:
			return

		# Setup connections and get parameters
		key = job["remote_id"]
		try:
			self.query = SearchQuery(key=key, db=self.db)
		except TypeError:
			self.log.info("Query job %s refers to non-existent query, finishing." % key)
			self.queue.finish_job(job)
			return

		if self.query.is_finished():
			self.log.info("Worker started for query %s, but query is already finished" % key)
			self.queue.finish_job(job)
			return

		# connect to Sphinx backend
		self.sphinx = MySQLDatabase(
			host="localhost",
			user=config.DB_USER,
			password=config.DB_PASSWORD,
			port=9306,
			logger=self.log
		)

		query_parameters = self.query.get_parameters()
		results_file = self.query.get_results_path()
		results_file = results_file.replace("*", "")

		posts = self.execute_query(query_parameters)
		if not posts:
			self.query.set_empty()
			self.query.update_status("Query finished, but no results were found.")
		else:
			self.posts_to_csv(posts, results_file)

		num_posts = len(posts) if posts else 0
		self.query.finish(num_rows=num_posts)
		self.queue.finish_job(job)

	def execute_query(self, query):
		"""
		Execute a query; get post data for given parameters

		This handles general search - anything that does not involve dense
		threads (those are handled by get_dense_threads()). First, Sphinx is
		queries with the search parameters to get the relevant post IDs; then
		the PostgreSQL is queried to return all posts for the found IDs, as
		well as (optionally) all other posts in the threads those posts were in.

		:param dict query:  Query parameters, as part of the SearchQuery object
		:return list:  Posts, sorted by thread and post ID, in ascending order
		"""

		# first, build the sphinx query
		where = []
		replacements = []
		match = []

		if query["min_date"]:
			where.append("timestamp >= %s")
			replacements.append(query["min_date"])

		if query["max_date"]:
			where.append("timestamp <= %s")
			replacements.append(query["max_date"])

		if query["board"]:
			where.append("board = %s")
			replacements.append(query["board"])

		if query["body_query"] and query["body_query"] != "empty":
			match.append("@body " + query["body_query"])

		if query["subject_query"] and query["subject_query"] != "empty":
			match.append("@subject " + query["subject_query"])

		# both possible FTS parameters go in one MATCH() operation
		if match:
			where.append("MATCH(%s)")
			replacements.append(" ".join(match))

		# query Sphinx
		self.query.update_status("Searching for matches")
		sphinx_start = time.time()
		where = " AND ".join(where)
		sql = "SELECT thread_id, post_id FROM `4cat_posts` WHERE " + where + " LIMIT 5000000 OPTION max_matches = 5000000"
		self.log.info("Running Sphinx query %s " % sql)

		try:
			posts = self.sphinx.fetchall(sql, replacements)
		except OperationalError:
			self.query.update_status("Your query timed out. This is likely because it matches too many posts. Try again with a narrower date range or a more specific search query.")
			self.log.info("Sphinx query (body: %s/subject: %s) timed out after %i seconds" % (query["body_query"], query["subject_query"], time.time() - sphinx_start))
			self.sphinx.close()
			return None

		self.log.info("Sphinx query finished in %i seconds, %i results." % (time.time() - sphinx_start, len(posts)))
		self.query.update_status("Found %i matches. Collecting post data" % len(posts))
		self.sphinx.close()

		if not posts:
			# no results
			return None

		# query posts database
		postgres_start = time.time()
		self.log.info("Running full posts query")
		columns = ", ".join(self.return_cols)

		if not query["full_thread"] and not query["dense_threads"]:
			# just the exact post IDs we found via Sphinx
			post_ids = tuple([post["post_id"] for post in posts])
			posts = self.db.fetchall("SELECT " + columns + " FROM posts WHERE id IN %s ORDER BY id ASC",
									 (post_ids,))
			self.query.update_status("Post data collected")
			self.log.info("Full posts query finished in %i seconds." % (time.time() - postgres_start))

		else:
			# all posts for all thread IDs found by Sphinx
			thread_ids = tuple([post["thread_id"] for post in posts])

			posts = self.db.fetchall(
				"SELECT " + columns + " FROM posts WHERE thread_id IN %s ORDER BY thread_id ASC, id ASC", (thread_ids,))

			# get dense thread ids
			if query["dense_threads"] and query["body_query"] != "empty":
				self.query.update_status("Post data collected. Filtering dense threads")
				posts = self.filter_dense(posts, query["body_query"], query["dense_percentage"], query["dense_length"])

				# When there are no dense threads
				if not posts:
					return []
			else:
				self.query.update_status("Post data collected")

			self.log.info("Full posts query finished in %i seconds." % (time.time() - postgres_start))

		return posts

	def filter_dense(self, posts, keyword, percentage, length):
		"""
		Filter posts for those in "dense threads"

		Dense threads are threads in which a given keyword contains more than
		a given amount of times. This takes a post array as returned by
		`execute_query()` and filters it so that only posts in threads in which
		the keyword appears more than a given threshold's amount of times
		remain.

		:param list posts:  Posts to filter, result of `execute_query()`
		:param string keyword:  Keyword that posts will be matched against
		:param float percentage:  How many posts in the thread need to qualify
		:param int length:  How long a thread needs to be to qualify
		:return list:  Filtered list of posts
		"""
		# for each thread, save number of posts and number of matching posts
		self.log.info("Filtering %s-dense threads from %i posts..." % (keyword, len(posts)))
		threads = {}
		for post in posts:
			if post["thread_id"] not in threads:
				threads[post["thread_id"]] = {"posts": 0, "match": 0}

			if keyword in post["body"]:
				threads[post["thread_id"]]["match"] += 1

			threads[post["thread_id"]]["posts"] += 1

		# filter out those threads with the right ratio
		filtered_threads = []
		percentage /= 100.0
		for thread in threads:
			if threads[thread]["posts"] > length and float(threads[thread]["match"]) / float(threads[thread]["posts"]) > percentage:
				filtered_threads.append(thread)

		self.log.info("Found %i %s-dense threads in results set" % (len(filtered_threads), keyword))
		self.query.update_status("Found %i %s-dense threads. Collecting final post set" % (len(filtered_threads), keyword))

		# filter posts that do not qualify
		filtered_posts = []
		while posts:
			post = posts[0]
			del posts[0]

			if post["thread_id"] in filtered_threads:
				filtered_posts.append(post)

		# return filtered list of posts
		self.log.info("%s-dense thread filtering finished, %i posts left." % (keyword, len(filtered_posts)))
		self.query.update_status("Dense thread filtering finished, %i posts left. Writing to file" % len(filtered_posts))
		return filtered_posts

	def filter_dense_sql(self, thread_ids, keyword, percentage, length):
		"""
		Filter posts for those in "dense threads"

		Dense threads are threads in which a given keyword contains more than
		a given amount of times. This takes a post array as returned by
		`execute_query()` and filters it so that only posts in threads in which
		the keyword appears more than a given threshold's amount of times
		remain.

		:param list thread_ids:  Threads to filter, result of `execute_query()`
		:param string keyword:  Keyword that posts will be matched against
		:param float percentage:  How many posts in the thread need to qualify
		:param int length:  How long a thread needs to be to qualify
		:return list:  Filtered list of posts
		"""
		# for each thread, save number of posts and number of matching posts
		self.log.debug("Filtering %s-dense threads from %i threads..." % (keyword, len(thread_ids)))

		try:
			threads = self.db.fetchall("""
				SELECT id as thread_id, num_replies, keyword_count, keyword_density::real FROM (
					SELECT id, num_replies, keyword_count, ((keyword_count::real / num_replies::real) * 100) AS keyword_density FROM (
						SELECT id, num_replies, count(*) as keyword_count FROM threads
						WHERE id IN %s
						GROUP BY id, num_replies
					) AS thread_matches
				) AS thread_meta
				WHERE num_replies >= %s
				AND keyword_density >= %s

				""", (thread_ids, length, percentage,))
		except Exception as error:
			return str(error)

		self.log.debug("Dense thread filtering finished, %i threads left." % len(threads))

		filtered_threads = tuple([thread['thread_id'] for thread in threads])
		
		return filtered_threads

	def posts_to_csv(self, sql_results, filepath, clean_csv=True):
		"""
		Takes a dictionary of results, converts it to a csv, and writes it to the data folder.
		The respective csvs will be available to the user.

		:param sql_results:		List with results derived with db.fetchall()
		:param filepath:    	Filepath for the resulting csv
		:param clean_csv:   	Whether to parse the raw HTML data to clean text.
								If True (default), writing takes 1.5 times longer.

		"""

		if not filepath:
			raise Exception("No result file for query")

		fieldnames = list(sql_results[0].keys())

		# write the dictionary to a csv
		with open(filepath, 'w', encoding='utf-8') as csvfile:
			self.query.update_status("Writing posts to result file")
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

		self.query.update_status("Query finished, results are available.")
		return filepath
