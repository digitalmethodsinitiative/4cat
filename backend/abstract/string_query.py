import time
import csv
import abc
import re

from pymysql import OperationalError
from collections import Counter

import config
from backend.lib.database_mysql import MySQLDatabase
from backend.lib.query import DataSet
from backend.abstract.worker import BasicWorker
from backend.lib.helpers import posts_to_csv

class StringQuery(BasicWorker, metaclass=abc.ABCMeta):
	"""
	Process substring queries from the front-end

	Requests are added to the pool as "query" jobs. This class is to be
	extended by platform-specific search classes, which will define the
	abstract methods at the end of this class to tailor the search engine
	to their database layouts.
	"""

	type = "query"
	max_workers = 2

	prefix = ""
	sphinx_index = ""

	sphinx = None
	query = None

	# Columns to return in csv
	# Mandatory columns: ['thread_id', 'body', 'subject', 'timestamp']
	return_cols = ['thread_id', 'id', 'timestamp', 'body', 'subject', 'author', 'image_file', 'image_md5',
				   'country_code']

	def work(self):
		"""
		Run 4CAT search query

		Gets query details, passes them on to the object's search method, and
		writes the results to a CSV file. If that all went well, the query and
		job are marked as finished.
		"""
		# Setup connections and get parameters
		key = self.job.data["remote_id"]
		try:
			self.query = DataSet(key=key, db=self.db)
		except TypeError:
			self.log.info("Query job %s refers to non-existent query, finishing." % key)
			self.job.finish()
			return

		if self.query.is_finished():
			self.log.info("Worker started for query %s, but query is already finished" % key)
			self.job.finish()
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

		# Execute the relevant query (string-based or random)
		if query_parameters["random_amount"]:
			posts = self.execute_random_query(query_parameters)
		else:
			posts = self.execute_string_query(query_parameters)

		# Write posts to csv and update the DataBase status to finished
		if posts:
			self.query.update_status("Writing posts to result file")
			posts_to_csv(posts, results_file)
			self.query.update_status("Query finished, results are available.")

		num_posts = len(posts) if posts else 0
		self.query.finish(num_rows=num_posts)
		self.job.finish()

	def execute_string_query(self, query):
		"""
		Execute a query; get post data for given parameters

		This handles general search - anything that does not involve dense
		threads (those are handled by get_dense_threads()). First, Sphinx is
		queries with the search parameters to get the relevant post IDs; then
		the PostgreSQL is queried to return all posts for the found IDs, as
		well as (optionally) all other posts in the threads those posts were in.

		:param dict query:  Query parameters, as part of the DataSet object
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

		if query["board"] and query["board"] != "*":
			where.append("board = %s")
			replacements.append(query["board"])

		# escape / since it's a special character for Sphinx
		if query["body_query"]:
			match.append("@body " + query["body_query"].replace("/", "\/").replace("(", "\(",).replace("*", "\*"))

		if query["subject_query"]:
			match.append("@subject " + query["subject_query"].replace("/", "\/").replace("(", "\(",).replace("*", "\*"))

		# both possible FTS parameters go in one MATCH() operation
		if match:
			where.append("MATCH(%s)")
			replacements.append(" ".join(match))

		# query Sphinx
		self.query.update_status("Searching for matches")
		sphinx_start = time.time()
		where = " AND ".join(where)

		try:
			posts = self.fetch_sphinx(where, replacements)
		except OperationalError:
			self.query.update_status(
				"Your query timed out. This is likely because it matches too many posts. Try again with a narrower date range or a more specific search query.")
			self.log.info("Sphinx query (body: %s/subject: %s) timed out after %i seconds" % (
			query["body_query"], query["subject_query"], time.time() - sphinx_start))
			self.sphinx.close()
			return None

		self.log.info("Sphinx query finished in %i seconds, %i results." % (time.time() - sphinx_start, len(posts)))
		self.query.update_status("Found %i matches. Collecting post data" % len(posts))
		self.sphinx.close()

		if not posts:
			# no results
			self.query.update_status("Query finished, but no results were found.")
			return None

		# query posts database
		postgres_start = time.time()
		self.log.info("Running full posts query")
		columns = ", ".join(self.return_cols)

		if not query["full_thread"] and not query["dense_threads"]:
			# just the exact post IDs we found via Sphinx
			post_ids = tuple([post["post_id"] for post in posts])
			posts = self.fetch_posts(post_ids)
			self.query.update_status("Post data collected")
			self.log.info("Full posts query finished in %i seconds." % (time.time() - postgres_start))

		else:
			# all posts for all thread IDs found by Sphinx
			thread_ids = tuple([post["thread_id"] for post in posts])

			# if indicated, get dense thread ids
			if query["dense_threads"] and query["body_query"]:
				self.query.update_status("Post data collected. Filtering dense threads")
				#posts = self.filter_dense(posts, query["body_query"], query["dense_percentage"], query["dense_length"])
				thread_ids = self.filter_dense(thread_ids, query["body_query"], query["dense_percentage"], query["dense_length"])

				# When there are no dense threads
				if not thread_ids:
					return []

			posts = self.fetch_threads(thread_ids)
			
			self.query.update_status("Post data collected")

			self.log.info("Full posts query finished in %i seconds." % (time.time() - postgres_start))

		return posts


	def execute_random_query(self, query):
		"""
		Execute a query; get post data for given parameters

		This handles general search - anything that does not involve dense
		threads (those are handled by get_dense_threads()). First, Sphinx is
		queries with the search parameters to get the relevant post IDs; then
		the PostgreSQL is queried to return all posts for the found IDs, as
		well as (optionally) all other posts in the threads those posts were in.

		:param dict query:  Query parameters, as part of the DataSet object
		:return list:  Posts, sorted by thread and post ID, in ascending order
		"""

		# Build random id query
		where = []
		replacements = []

		# Amount of random posts to get
		random_amount = query["random_amount"]

		# Set dates
		if query["max_date"] == 0:
			max_date = 1000000000
		else:
			max_date = query["max_date"]
		min_date = query["min_date"]
		# Get random post ids
		# Use `if`s since you can't use a variable for tables
		if self.prefix == "4chan":
			post_ids = self.db.fetchall("""SELECT id FROM posts_4chan ORDER BY random() LIMIT %s;
			""", (random_amount,))
		elif self.prefix == '8chan':
			post_ids = self.db.fetchall("""SELECT id FROM posts_8chan ORDER BY random() LIMIT %s;
			""", (random_amount,))
		else:
			raise Exception("Invalid prefix %s" % (self.prefix))

		# Fetch the posts
		post_ids =  tuple([post["id"] for post in post_ids])
		posts = self.fetch_posts(post_ids)
		self.query.update_status("Post data collected")

		return posts

	def filter_dense(self, thread_ids, keyword, percentage, length):
		"""
		Filter posts for those in "dense threads"

		Dense threads are threads in which a given keyword contains more than
		a given amount of times. This takes a post array as returned by
		`execute_string_query()` and filters it so that only posts in threads in which
		the keyword appears more than a given threshold's amount of times
		remain.

		:param list thread_ids:  Threads to filter, result of `execute_string_query()`
		:param string keyword:  Keyword that posts will be matched against
		:param float percentage:  How many posts in the thread need to qualify
		:param int length:  How long a thread needs to be to qualify
		:return list:  Filtered list of posts
		"""
		# for each thread, save number of posts and number of matching posts
		self.log.info("Filtering %s-dense threads from %i threads..." % (keyword, len(thread_ids)))

		keyword_posts = Counter(thread_ids)

		# if statements becuase you can't use a variable as a table header...
		if self.prefix == "4chan":
			total_posts = self.db.fetchall("""SELECT id, num_replies FROM threads_4chan
												WHERE id IN %s
												GROUP BY id
			""", (thread_ids,))
		elif self.prefix == '8chan':
			thread_ids = tuple([str(thread_id) for thread_id in thread_ids])
			total_posts = self.db.fetchall("""SELECT id, num_replies FROM threads_8chan
												WHERE id IN %s
												GROUP BY id
			""", (thread_ids,))
		else:
			raise Exception("Invalid prefix %s" % (self.prefix))

		# check wether the total posts / posts with keywords is longer than the given percentage,
		# and if the length is above the given threshold
		qualified_threads = []
		for total_post in total_posts:
			# check if the length meets the threshold
			if total_post["num_replies"] >= length:
				# check if the keyword density meets the threshold
				thread_density = float(keyword_posts[total_post["id"]] / total_post["num_replies"] * 100)
				if thread_density >= float(percentage):
					qualified_threads.append(total_post["id"])


		self.log.info("Dense thread filtering finished, %i threads left." % len(qualified_threads))
		filtered_threads = tuple([thread for thread in qualified_threads])
		return filtered_threads

	@abc.abstractmethod
	def fetch_posts(self, post_ids):
		pass

	@abc.abstractmethod
	def fetch_threads(self, thread_ids):
		pass

	@abc.abstractmethod
	def fetch_sphinx(self, where, replacements):
		pass
