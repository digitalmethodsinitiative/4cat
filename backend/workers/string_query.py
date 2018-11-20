import time
import csv
import os

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
			query = SearchQuery(key=key, db=self.db)
		except TypeError:
			self.log.info("Query job %s refers to non-existent query, finishing." % key)
			self.queue.finish_job(job)
			return

		if query.is_finished():
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

		query_parameters = query.get_parameters()
		results_file = query.get_results_path()
		results_file = results_file.replace("*", "")

		posts = self.execute_query(query_parameters)
		if not posts:
			query.set_empty()
		else:
			self.posts_to_csv(posts, results_file)

		query.finish()
		self.queue.finish_job(job)
		self.sphinx.close()

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
		sphinx_start = time.time()
		where = " AND ".join(where)
		sql = "SELECT thread_id, post_id FROM `4cat_posts` WHERE " + where + " LIMIT 5000000 OPTION max_matches = 5000000"
		self.log.info("Running Sphinx query %s " % sql)
		posts = self.sphinx.fetchall(sql, replacements)
		self.log.info("Sphinx query finished in %i seconds, %i results." % (time.time() - sphinx_start, len(posts)))
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
			self.log.info("Full posts query finished in %i seconds." % (time.time() - postgres_start))

		else:
			# all posts for all thread IDs found by Sphinx
			thread_ids = tuple([post["thread_id"] for post in posts])
			posts = self.db.fetchall(
				"SELECT " + columns + " FROM posts WHERE thread_id IN %s ORDER BY thread_id ASC, id ASC", (thread_ids,))
			self.log.info("Full posts query finished in %i seconds." % (time.time() - postgres_start))

			if query["dense_threads"] and query["body_query"] != "empty":
				posts = self.filter_dense(posts, query["body_query"], query["dense_percentage"], query["dense_length"])

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
			if float(threads[thread]["match"]) / float(threads[thread]["posts"]) > percentage:
				filtered_threads.append(thread)

		self.log.info("Found %i %s-dense threads in results set" % (len(filtered_threads), keyword))

		# filter posts that do not qualify
		filtered_posts = []
		while posts:
			post = posts[0]
			del posts[0]

			if post["thread_id"] in filtered_threads:
				filtered_posts.append(post)

		# return filtered list of posts
		self.log.info("Dense thread filtering finished, %i posts left." % len(filtered_posts))
		return filtered_posts

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
