import time
import csv
import abc
import re
import html2text

from pymysql import OperationalError
from collections import Counter

import config
from backend.lib.database_mysql import MySQLDatabase
from backend.lib.query import SearchQuery
from backend.abstract.worker import BasicWorker


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
			self.query = SearchQuery(key=key, db=self.db)
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

		posts = self.execute_query(query_parameters)
		if not posts:
			self.query.set_empty()
		else:
			self.posts_to_csv(posts, results_file)

		num_posts = len(posts) if posts else 0
		self.query.finish(num_rows=num_posts)
		self.job.finish()

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

		if query["board"] and query["board"] != "*":
			where.append("board = %s")
			replacements.append(query["board"])

		# escape / since it's a special character for Sphinx
		if query["body_query"]:
			match.append("@body " + query["body_query"].replace("/", "\/"))

		if query["subject_query"]:
			match.append("@subject " + query["subject_query"].replace("/", "\/"))

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
				thread_ids = self.filter_dense_sql(thread_ids, query["body_query"], query["dense_percentage"], query["dense_length"])

				# When there are no dense threads
				if not thread_ids:
					return []

			posts = self.fetch_threads(thread_ids)
			
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
			if threads[thread]["posts"] > length and float(threads[thread]["match"]) / float(
					threads[thread]["posts"]) > percentage:
				filtered_threads.append(thread)

		self.log.info("Found %i %s-dense threads in results set" % (len(filtered_threads), keyword))
		self.query.update_status(
			"Found %i %s-dense threads. Collecting final post set" % (len(filtered_threads), keyword))

		# filter posts that do not qualify
		filtered_posts = []
		while posts:
			post = posts[0]
			del posts[0]

			if post["thread_id"] in filtered_threads:
				filtered_posts.append(post)

		# return filtered list of posts
		self.log.info("%s-dense thread filtering finished, %i posts left." % (keyword, len(filtered_posts)))
		self.query.update_status(
			"Dense thread filtering finished, %i posts left. Writing to file" % len(filtered_posts))
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
		fieldnames.append("unix_timestamp")

		# write the dictionary to a csv
		with open(filepath, 'w', encoding='utf-8') as csvfile:
			self.query.update_status("Writing posts to result file")
			writer = csv.DictWriter(csvfile, fieldnames=fieldnames, lineterminator='\n')
			writer.writeheader()

			html_parser = html2text.HTML2Text()

			if clean_csv:
				# Parsing: remove the HTML tags, but keep the <br> as a newline
				# Takes around 1.5 times longer
				for row in sql_results:
					# Create human dates from timestamp
					from datetime import datetime
					row["unix_timestamp"] = row["timestamp"]
					row["timestamp"] = datetime.utcfromtimestamp(row["timestamp"]).strftime('%Y-%m-%d %H:%M:%S')

					# Parse html to text
					row["body"] = html_parser.handle(row["body"])

					writer.writerow(row)
			else:
				writer.writerows(sql_results)

		self.query.update_status("Query finished, results are available.")
		return filepath

	@abc.abstractmethod
	def fetch_posts(self, post_ids):
		pass

	@abc.abstractmethod
	def fetch_threads(self, thread_ids):
		pass

	@abc.abstractmethod
	def fetch_sphinx(self, where, replacements):
		pass
