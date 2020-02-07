"""
4chan Search via Sphinx
"""
import time
import re

from pymysql import OperationalError, ProgrammingError, Error

import config
from backend.lib.database_mysql import MySQLDatabase
from backend.abstract.search import Search
from backend.lib.exceptions import QueryParametersException, ProcessorInterruptedException


class Search4Chan(Search):
	"""
	Search 4chan corpus

	Defines methods that are used to query the 4chan data indexed and saved.
	"""
	type = "4chan-search"  # job ID
	sphinx_index = "4chan"  # prefix for sphinx indexes for this data source. Should usually match sphinx.conf
	prefix = "4chan"  # table identifier for this datasource; see below for usage

	# Columns to return in csv
	return_cols = ['thread_id', 'id', 'timestamp', 'body', 'subject', 'author', 'image_file', 'image_md5',
				   'country_code', 'country_name']

	# codes for countries that can be selected under one "european countries"
	# umbrella
	eu_countries = (
		"GB", "DE", "NL", "RU", "FI", "FR", "RO", "PL", "SE", "NO", "ES", "IE", "IT", "SI", "RS", "DK", "HR", "GR",
		"BG",
		"BE", "AT", "HU", "CH", "PT", "LT", "CZ", "EE", "UY", "LV", "SK", "MK", "UA", "IS", "BA", "CY", "GE", "LU",
		"ME",
		"AL", "MD", "IM", "EU", "BY", "MC", "AX", "KZ", "AM", "GG", "JE", "MT", "FO", "AZ", "LI", "AD")

	def get_posts_simple(self, query):
		"""
		Fast-lane for simpler queries that don't need the intermediate step
		where Sphinx is queried

		In practice this means queries that only select by time period,
		country code and/or random sample
		:param query:
		:return:
		"""
		where = []
		replacements = [query.get("board", "")]

		if query.get("min_date", 0):
			try:
				where.append("p.timestamp >= %s")
				replacements.append(int(query.get("min_date")))
			except ValueError:
				pass

		if query.get("max_date", 0):
			try:
				replacements.append(int(query.get("max_date")))
				where.append("p.timestamp < %s")
			except ValueError:
				pass

		if query.get("country_code", None) and query.get("country_code") != "all":
			if query.get("p.country_code") == "eu":
				where.append("country_code IN %s")
				replacements.append(self.eu_countries)
			else:
				where.append("p.country_code = %s")
				replacements.append(query.get("country_code"))

		sql_query = ("SELECT p.*, t.board " \
					 "FROM posts_" + self.prefix + " AS p " \
					 "LEFT JOIN threads_" + self.prefix + " AS t " \
					 "ON t.id = p.thread_id " \
					 "WHERE t.board = %s ")

		if where:
			sql_query += " AND " + " AND ".join(where)

		if query.get("search_scope", None) == "random-sample":

			try:
				sample_size = int(query.get("sample_size", 5000))
				sql_query = "SELECT * FROM (" + sql_query +  " ORDER BY RANDOM() LIMIT " + str(int(query.get("random_amount", 0))) + ") AS full_table ORDER BY full_table.timestamp ASC"
			
			except ValueError:
				pass
		else:
			sql_query += " ORDER BY p.timestamp ASC"

		return self.db.fetchall_interruptable(self.queue, sql_query, replacements)

	def get_posts_complex(self, query):
		"""
		Complex queries that require full-text search capabilities

		This adds an intermediate step where Sphinx is queried to get IDs for
		matching posts, which are then handled further.

		As much as possible is pre-selected through Sphinx, and then the rest
		is handled through PostgreSQL queries.

		:param dict query:  Query parameters, as part of the DataSet object
		:return list:  Posts, sorted by thread and post ID, in ascending order
		"""

		# first, build the sphinx query
		where = []
		replacements = []
		match = []

		if query.get("min_date", None):
			try:
				if int(query.get("min_date")) > 0:
					where.append("timestamp >= %s")
					replacements.append(int(query.get("min_date")))
			except ValueError:
				pass

		if query.get("max_date", None):
			try:
				if int(query.get("max_date")) > 0:
					replacements.append(int(query.get("max_date")))
					where.append("timestamp < %s")
			except ValueError:
				pass

		if query.get("board", None) and query["board"] != "*":
			where.append("board = %s")
			replacements.append(query["board"])

		# escape full text matches
		if query.get("body_match", None):
			match.append("@body " + self.escape_for_sphinx(query["body_match"]))

		if query.get("subject_match", None):
			match.append("@subject " + self.escape_for_sphinx(query["subject_match"]))

		# handle country codes through sphinx if not looking for density
		if query.get("country_code", None) and not query.get("check_dense_country", None) and query.get(
				"country_code") != "all":
			if query.get("country_code", "") == "eu":
				where.append("country_code IN %s")
				replacements.append(self.eu_countries)
			else:
				where.append("country_code = %s")
				replacements.append(query.get("country_code"))

		# both possible FTS parameters go in one MATCH() operation
		if match:
			where.append("MATCH(%s)")
			replacements.append(" ".join(match))

		# query Sphinx
		self.dataset.update_status("Searching for matches")
		where = " AND ".join(where)

		posts = self.fetch_sphinx(where, replacements)
		if posts is None:
			return posts
		elif len(posts) == 0:
			# no results
			self.dataset.update_status("Query finished, but no results were found.")
			return None


		# query posts database
		self.dataset.update_status("Found %i matches. Collecting post data" % len(posts))
		datafetch_start = time.time()
		self.log.info("Collecting post data from database")
		columns = ", ".join(self.return_cols)

		postgres_where = []
		postgres_replacements = []

		if query.get("country_code", None) and not query.get("country_code") == "all":
			if query.get("country_code") == "eu":
				postgres_where.append("country_code IN %s")
				postgres_replacements.append(self.eu_countries)
			else:
				postgres_where.append("country_code = %s")
				postgres_replacements.append(query.get("country_code"))

		posts_full = self.fetch_posts(tuple([post["post_id"] for post in posts]), postgres_where, postgres_replacements)

		self.dataset.update_status("Post data collected")
		self.log.info("Full posts query finished in %i seconds." % (time.time() - datafetch_start))

		return posts_full

	def escape_for_sphinx(self, string):
		"""
		SphinxQL has a couple of special characters that should be escaped if
		they are part of a query, but no native function is available to
		provide this functionality. This method does.

		Thanks: https://stackoverflow.com/a/6288301

		:param str string:  String to escape
		:return str: Escaped string
		"""
		return string.replace("/", "\\/")

	def fetch_posts(self, post_ids, where=None, replacements=None):
		"""
		Fetch post data from database

		:param list post_ids:  List of post IDs to return data for
		:return list: List of posts, with a dictionary representing the database record for each post
		"""
		if not where:
			where = []

		if not replacements:
			replacements = []

		columns = ", ".join(self.return_cols)
		where.append("id IN %s")
		replacements.append(post_ids)

		if self.interrupted:
			raise ProcessorInterruptedException("Interrupted while fetching post data")

		query = "SELECT " + columns + " FROM posts_" + self.prefix + " WHERE " + " AND ".join(
			where) + " ORDER BY id ASC"
		return self.db.fetchall_interruptable(self.queue, query, replacements)

	def fetch_threads(self, thread_ids):
		"""
		Fetch post from database for given threads

		:param list thread_ids: List of thread IDs to return post data for
		:return list: List of posts, with a dictionary representing the database record for each post
		"""
		columns = ", ".join(self.return_cols)

		if self.interrupted:
			raise ProcessorInterruptedException("Interrupted while fetching thread data")

		return self.db.fetchall_interruptable(self.queue,
			"SELECT " + columns + " FROM posts_" + self.prefix + " WHERE thread_id IN %s ORDER BY thread_id ASC, id ASC",
											  (thread_ids,))

	def fetch_sphinx(self, where, replacements):
		"""
		Query Sphinx for matching post IDs

		:param str where:  Drop-in WHERE clause (without the WHERE keyword) for the Sphinx query
		:param list replacements:  Values to use for parameters in the WHERE clause that should be parsed
		:return list:  List of matching posts; each post as a dictionary with `thread_id` and `post_id` as keys
		"""

		sphinx_start = time.time()
		sphinx = MySQLDatabase(
			host="localhost",
			user=config.DB_USER,
			password=config.DB_PASSWORD,
			port=9306,
			logger=self.log
		)

		try:
			sql = "SELECT thread_id, post_id FROM `" + self.prefix + "_posts` WHERE " + where + " LIMIT 5000000 OPTION max_matches = 5000000, ranker = none, boolean_simplify = 1, sort_method = kbuffer, cutoff = 5000000"
			# sql = "SELECT thread_id, post_id FROM `" + self.prefix + "_posts` WHERE " + where + " LIMIT 5000000 OPTION max_matches = 5000000, ranker = none, boolean_simplify = 1, sort_method = kbuffer, cutoff = 5000000"
			self.log.info("Running Sphinx query %s " % sql)
			self.log.info("Parameters: %s " % repr(replacements))
			results = sphinx.fetchall(sql, replacements)
			sphinx.close()
			self.log.info(
				"Sphinx query finished in %i seconds, %i results." % (time.time() - sphinx_start, len(results)))
		except OperationalError:
			self.dataset.update_status(
				"Your query timed out. This is likely because it matches too many posts. Try again with a narrower date range or a more specific search query.")
			self.log.info("Sphinx query timed out after %i seconds" % (time.time() - sphinx_start))
			return None
		except ProgrammingError as e:
			self.dataset.update_status("Error during query. Your query syntax may be invalid (check for loose parentheses).")
			self.log.error("Sphinx crash during query %s: %s" % (self.dataset.key, e))
			return None

		return results

	def get_thread_sizes(self, thread_ids, min_length):
		"""
		Get thread lengths for all threads

		:param tuple thread_ids:  List of thread IDs to fetch lengths for
		:param int min_length:  Min length for a thread to be included in the
		results
		:return dict:  Threads sizes, with thread IDs as keys
		"""
		# find total thread lengths for all threads in initial data set
		thread_sizes = {row["thread_id"]: row["num_posts"] for row in self.db.fetchall_interruptable(
			self.queue, "SELECT COUNT(*) as num_posts, thread_id FROM posts_" + self.prefix + " WHERE thread_id IN %s GROUP BY thread_id",
			(thread_ids,)) if int(row["num_posts"]) > min_length}

		return thread_sizes

	def validate_query(query, request):
		"""
		Validate input for a dataset query on the 4chan data source.

		Will raise a QueryParametersException if invalid parameters are
		encountered. Mutually exclusive parameters may also be sanitised by
		ignoring either of the mutually exclusive options.

		:param dict query:  Query parameters, from client-side.
		:param request:  Flask request
		:return dict:  Safe query parameters
		"""

		# this is the bare minimum, else we can't narrow down the full data set
		if not query.get("body_match", None) and not query.get("subject_match", None) and query.get("search_scope",	"") != "random-sample":
			raise QueryParametersException("Please provide a body query, subject query or random sample size.")

		# Make sure to accept only a body or subject match.
		if not query.get("body_match", None) and query.get("subject_match", None):
			query["body_match"] = ""
		elif query.get("body_match", None) and not query.get("subject_match", None):
			query["subject_match"] = ""

		# body query and full threads are incompatible, returning too many posts
		# in most cases
		if query.get("body_match", None):
			if "full_threads" in query:
				del query["full_threads"]

		# random sample requires a sample size, and is additionally incompatible
		# with full threads
		if query.get("search_scope", "") == "random-sample":
			try:
				sample_size = int(query.get("random_amount", 0))
			except ValueError:
				raise QueryParametersException("Please provide a valid numerical sample size.")

			if sample_size < 1 or sample_size > 100000:
				raise QueryParametersException("Please provide a sample size between 1 and 100000.")

			if "full_threads" in query:
				del query["full_threads"]

		# only one of two dense threads options may be chosen at the same time, and
		# it requires valid density and length parameters. full threads is implied,
		# so it is otherwise left alone here
		if query.get("search_scope", "") == "dense-threads":
			try:
				dense_density = int(query.get("scope_density", ""))
			except ValueError:
				raise QueryParametersException("Please provide a valid numerical density percentage.")

			if dense_density < 15 or dense_density > 100:
				raise QueryParametersException("Please provide a density percentage between 15 and 100.")

			try:
				dense_length = int(query.get("scope_length", ""))
			except ValueError:
				raise QueryParametersException("Please provide a valid numerical dense thread length.")

			if dense_length < 30:
				raise QueryParametersException("Please provide a dense thread length of at least 30.")

		# both dates need to be set, or none
		if query.get("min_date", None) and not query.get("max_date", None):
			raise QueryParametersException("When setting a date range, please provide both an upper and lower limit.")

		# the dates need to make sense as a range to search within
		if query.get("min_date", None) and query.get("max_date", None):
			try:
				before = int(query.get("max_date", ""))
				after = int(query.get("min_date", ""))
			except ValueError:
				raise QueryParametersException("Please provide valid dates for the date range.")

			if before < after:
				raise QueryParametersException(
					"Please provide a valid date range where the start is before the end of the range.")

			query["min_date"] = after
			query["max_date"] = before

		is_placeholder = re.compile("_proxy$")
		filtered_query = {}
		for field in query:
			if not is_placeholder.search(field):
				filtered_query[field] = query[field]

		# if we made it this far, the query can be executed
		return filtered_query
