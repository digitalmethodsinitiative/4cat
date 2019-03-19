import time
import csv
import abc
import re

from pymysql import OperationalError
from collections import Counter

import config

from backend.lib.database_mysql import MySQLDatabase
from backend.lib.query import SearchQuery
from backend.abstract.worker import BasicWorker
from backend.lib.helpers import posts_to_csv

class RandomQuery(BasicWorker, metaclass=abc.ABCMeta):
	"""
	Process random sample queries from the front-end

	Requests are added to the pool as "query" jobs. This class is to be
	extended by platform-specific search classes, which will define the
	abstract methods at the end of this class to tailor the search engine
	to their database layouts.
	"""

	type = "query"
	max_workers = 2

	prefix = ""

	query = None

	# Columns to return in csv
	# Mandatory columns: ['thread_id', 'body', 'subject', 'timestamp']
	return_cols = ['thread_id', 'id', 'timestamp', 'body', 'subject', 'author', 'image_file', 'image_md5',
				   'country_code']

	def work(self):
		"""
		Run 4CAT random sample query

		Gets a set of random posts and writes the results to a CSV file.
		If that all went well, the query and job are marked as finished.
		"""
		# Setup connections and get parameters
		key = self.job.data["remote_id"]
		try:
			self.query = SearchQuery(key=key, db=self.db)
		except TypeError:
			self.log.info("Query job %s refers to non-existent query, finishing." % key)
			self.job.finish()
			return

		if self.query.is_finished():
			self.log.info("Worker started for query %s, but query is already finished" % key)
			self.job.finish()
			return

		query_parameters = self.query.get_parameters()
		results_file = self.query.get_results_path()
		results_file = results_file.replace("*", "")

		posts = self.execute_random_query(query_parameters)

		if posts:
			self.posts_to_csv(posts, results_file)

		num_posts = len(posts) if posts else 0
		self.query.finish(num_rows=num_posts)
		self.job.finish()

	def execute_random_query(self, query):
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

		# build random id query
		where = []

		# amount of random posts to get
		post_limit = str(query["post_limit"])

		if query["min_date"]:
			where.append("timestamp >= " + query["min_date"])

		if query["max_date"]:
			where.append("timestamp <= " + query["max_date"])

		if query["board"] and query["board"] != "*":
			where.append("board = " + query["board"])

		where = " AND ".join(where)

		sql_query = "SELECT id FROM posts_" + self.prefix + " 'WHERE " + where + " ORDER BY random() LIMIT " + post_limit + ";"
		post_ids = self.db.fetchall(sql_query)

		self.fetch_posts(post_ids)
		self.query.update_status("Post data collected")

		return posts

	@abc.abstractmethod
	def fetch_posts(self, post_ids):
		pass

	@abc.abstractmethod
	def fetch_threads(self, thread_ids):
		pass

	@abc.abstractmethod
	def fetch_sphinx(self, where, replacements):
		pass
