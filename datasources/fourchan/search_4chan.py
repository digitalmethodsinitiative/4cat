"""
4chan Search via Sphinx
"""
import warnings
import time

from pymysql import OperationalError, ProgrammingError
from pymysql.err import Warning as SphinxWarning

import config
from backend.lib.database_mysql import MySQLDatabase
from common.lib.helpers import UserInput
from backend.abstract.search import SearchWithScope
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException


class Search4Chan(SearchWithScope):
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
		"BG", "BE", "AT", "HU", "CH", "PT", "LT", "CZ", "EE", "UY", "LV", "SK", "MK", "UA", "IS", "BA", "CY", "GE",
		"LU", "ME", "AL", "MD", "IM", "EU", "BY", "MC", "AX", "KZ", "AM", "GG", "JE", "MT", "FO", "AZ", "LI", "AD")

	# before running a sphinx query, store it here so it can be cancelled via
	# request_abort() later
	running_query = ""

	options = {
		"intro": {
			"type": UserInput.OPTION_INFO,
			"help": "Results are limited to 5 million items maximum. Be sure to read the [query "
					"syntax](/page/query-syntax/) for local data sources first - your query design will "
					"significantly impact the results. Note that large queries can take a long time to complete!"
		},
		"board": {
			"type": UserInput.OPTION_CHOICE,
			"options": {b: b for b in config.DATASOURCES[prefix].get("boards", [])},
			"help": "Board",
			"default": config.DATASOURCES[prefix].get("boards", [""])[0]
		},
		"body_match": {
			"type": UserInput.OPTION_TEXT,
			"help": "Post contains"
		},
		"subject_match": {
			"type": UserInput.OPTION_TEXT,
			"help": "Subject contains"
		},
		"country_code": {
			"type": UserInput.OPTION_CHOICE,
			"help": "Poster country",
			"options": {
				"all": "All countries",
				"europe": "All European countries",
				"US": "United States",
				"GB": "United Kingdom",
				"CA": "Canada",
				"AU": "Australia",
				"DE": "Germany",
				"NL": "Netherlands",
				"RU": "Russian Federation",
				"FI": "Finland",
				"FR": "France",
				"BR": "Brazil",
				"RO": "Romania",
				"PL": "Poland",
				"SE": "Sweden",
				"NO": "Norway",
				"XX": "Unknown",
				"NZ": "New Zealand",
				"ES": "Spain",
				"IE": "Ireland",
				"IT": "Italy",
				"SI": "Slovenia",
				"RS": "Serbia",
				"IN": "India",
				"DK": "Denmark",
				"MX": "Mexico",
				"HR": "Croatia",
				"GR": "Greece",
				"JP": "Japan",
				"BG": "Bulgaria",
				"AR": "Argentina",
				"IL": "Israel",
				"BE": "Belgium",
				"AT": "Austria",
				"HU": "Hungary",
				"CH": "Switzerland",
				"PT": "Portugal",
				"LT": "Lithuania",
				"CZ": "Czech Republic",
				"EE": "Estonia",
				"UY": "Uruguay",
				"ZA": "South Africa",
				"LV": "Latvia",
				"SK": "Slovakia",
				"MK": "Macedonia",
				"VN": "Vietnam",
				"CL": "Chile",
				"UA": "Ukraine",
				"PH": "Philippines",
				"SA": "Saudi Arabia",
				"KR": "South Korea",
				"DO": "Dominican Republic",
				"DZ": "Algeria",
				"SG": "Singapore",
				"MY": "Malaysia",
				"IS": "Iceland",
				"BA": "Bosnia and Herzegovina",
				"JO": "Jordan",
				"TH": "Thailand",
				"HK": "Hong Kong",
				"CY": "Cyprus",
				"PE": "Peru",
				"PR": "Puerto Rico",
				"LB": "Lebanon",
				"PK": "Pakistan",
				"CO": "Colombia",
				"IQ": "Iraq",
				"CR": "Costa Rica",
				"BD": "Bangladesh",
				"GE": "Georgia",
				"LU": "Luxembourg",
				"EG": "Egypt",
				"TW": "Taiwan",
				"ME": "Montenegro",
				"AL": "Albania",
				"VE": "Venezuela",
				"AE": "United Arab Emirates",
				"NP": "Nepal",
				"TR": "Turkey",
				"MD": "Moldova",
				"NG": "Nigeria",
				"PA": "Panama",
				"BZ": "Belize",
				"TN": "Tunisia",
				"TT": "Trinidad and Tobago",
				"IM": "Isle of Man",
				"KG": "Kyrgyzstan",
				"GT": "Guatemala",
				"BM": "Bermuda",
				"ID": "Indonesia",
				"BW": "Botswana",
				"BO": "Bolivia",
				"PY": "Paraguay",
				"MU": "Mauritius",
				"CN": "China",
				"KE": "Kenya",
				"KW": "Kuwait",
				"EU": "Europe",
				"MW": "Malawi",
				"BY": "Belarus",
				"MN": "Mongolia",
				"EC": "Ecuador",
				"MC": "Monaco",
				"AF": "Afghanistan",
				"AX": "Aland",
				"CW": "Curaçao",
				"VC": "Saint Vincent and the Grenadines",
				"MR": "Mauritania",
				"CU": "Cuba",
				"KZ": "Kazakhstan",
				"AM": "Armenia",
				"GG": "Guernsey",
				"BS": "Bahamas",
				"JE": "Jersey",
				"AW": "Aruba",
				"SV": "El Salvador",
				"HN": "Honduras",
				"LK": "Sri Lanka",
				"MT": "Malta",
				"FO": "Faroe Islands",
				"NC": "New Caledonia",
				"KH": "Cambodia",
				"MA": "Morocco",
				"FJ": "Fiji Islands",
				"BT": "Bhutan",
				"AO": "Angola",
				"QA": "Qatar",
				"BB": "Barbados",
				"AZ": "Azerbaijan",
				"LI": "Liechtenstein",
				"RE": "Réunion",
				"CM": "Cameroon",
				"JM": "Jamaica",
				"UG": "Uganda",
				"KY": "Cayman Islands",
				"AD": "Andorra",
				"IR": "Iran",
				"GU": "Guam",
				"MZ": "Mozambique",
				"MO": "Macao",
				"DJ": "Djibouti",
				"LY": "Libya",
				"MM": "Myanmar",
				"VI": "U.S. Virgin Islands",
				"SC": "Seychelles",
				"ET": "Ethiopia",
				"PS": "Palestine",
				"TZ": "Tanzania"
			},
			"default": "all"
		},
		"divider": {
			"type": UserInput.OPTION_DIVIDER
		},
		"daterange": {
			"type": UserInput.OPTION_DATERANGE,
			"help": "Date range"
		},
		"search_scope": {
			"type": UserInput.OPTION_CHOICE,
			"help": "Search scope",
			"options": {
				"posts-only": "All matching posts",
				"full-threads": "All posts in threads with matching posts (full threads)",
				"dense-threads": "All posts in threads in which at least x% of posts match (dense threads)",
				"match-ids": "Only posts matching the given post IDs"
			},
			"default": "posts-only"
		},
		"scope_density": {
			"type": UserInput.OPTION_TEXT,
			"help": "Min. density %",
			"min": 0,
			"max": 100,
			"default": 15,
			"tooltip": "At least this many % of posts in the thread must match the query"
		},
		"scope_length": {
			"type": UserInput.OPTION_TEXT,
			"help": "Min. dense thread length",
			"min": 30,
			"default": 30,
			"tooltip": "A thread must at least be this many posts long to qualify as a 'dense thread'"
		},
		"valid_ids": {
			"type": UserInput.OPTION_TEXT,
			"help": "Post IDs (comma-separated)"
		}
	}

	def get_items_simple(self, query):
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

		if query.get("search_scope", None) == "match-ids":
			try:
				query_ids = query.get("valid_ids", None)

				# Parse query IDs
				if query_ids:
					query_ids = query_ids.split(",")
					valid_query_ids = []
					for query_id in query_ids:
						try:
							# Make sure the text can be parsed to an integer.
							query_id = int(query_id.strip())
							valid_query_ids.append(str(query_id))
						except ValueError:
							# If not, just skip it.
							continue
					if not valid_query_ids:
						self.dataset.update_status("The IDs inserted are not valid 4chan post IDs.")
						return None

					if len(valid_query_ids) > 5000000:
						self.dataset.update_status("Too many IDs inserted. Max 5.000.000.")
						return None

					valid_query_ids = "(" + ",".join(valid_query_ids) + ")"
					sql_query = "SELECT * FROM (" + sql_query + "AND p.id IN " + valid_query_ids + ") AS full_table ORDER BY full_table.timestamp ASC"

				else:
					self.dataset.update_status("No 4chan post IDs inserted.")
					return None

			except ValueError:
				pass

		else:
			sql_query += " ORDER BY p.timestamp ASC"

		return self.db.fetchall_interruptable(self.queue, sql_query, replacements)

	def get_items_complex(self, query):
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

		# escape full text matches and convert quotes
		if query.get("body_match", None):
			match.append("@body " + self.convert_for_sphinx(query["body_match"]))

		if query.get("subject_match", None):
			match.append("@subject " + self.convert_for_sphinx(query["subject_match"]))

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

		# postgres_where.append("board = %s")
		# postgres_replacements.append(query.get("board"))

		posts_full = self.fetch_posts(tuple([post["post_id"] for post in posts]), postgres_where, postgres_replacements)

		self.dataset.update_status("Post data collected")
		self.log.info("Full posts query finished in %i seconds." % (time.time() - datafetch_start))

		return posts_full

	def convert_for_sphinx(self, string):
		"""
		SphinxQL has a couple of special characters that should be escaped if
		they are part of a query, but no native function is available to
		provide this functionality. This method provides it.

		Thanks: https://stackoverflow.com/a/6288301

		Also converts curly quotes to straight quotes to catch users copy-pasting
		their search full match queries from e.g. word.

		:param str string:  String to escape
		:return str: Escaped string
		"""

		# Convert curly quotes
		string = string.replace("“", "\"").replace("”", "\"")
		# Escape forward slashes
		string = string.replace("/", "\\/")
		# Escape @
		string = string.replace("@", "\\@")
		return string

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

		# if a Sphinx query is interrupted, pymysql will not actually raise an
		# exception but just a warning. But we need to detect interruption, so here we
		# make sure pymysql warnings are converted to exceptions
		warnings.filterwarnings("error", module=".*pymysql.*")

		sphinx_start = time.time()
		sphinx = self.get_sphinx_handler()

		results = []
		try:
			sql = "SELECT thread_id, post_id FROM `" + self.prefix + "_posts` WHERE " + where + " LIMIT 5000000 OPTION max_matches = 5000000, ranker = none, boolean_simplify = 1, sort_method = kbuffer, cutoff = 5000000"
			parsed_query = sphinx.mogrify(sql, replacements)
			self.log.info("Running Sphinx query %s " % parsed_query)
			self.running_query = parsed_query
			results = sphinx.fetchall(parsed_query, [])
			sphinx.close()
		except SphinxWarning as e:
			# this is a pymysql warning converted to an exception
			if "query was killed" in str(e):
				self.dataset.update_status("Search was interruped and will restart later")
				raise ProcessorInterruptedException("Interrupted while running Sphinx query")
			else:
				self.dataset.update_status("Error while querying full-text search index", is_final=True)
				self.log.error("Sphinx warning: %s" % e)
		except OperationalError as e:
			self.dataset.update_status(
				"Your query timed out. This is likely because it matches too many posts. Try again with a narrower date range or a more specific search query.",
				is_final=True)
			self.log.info("Sphinx query timed out after %i seconds" % (time.time() - sphinx_start))
			return None
		except ProgrammingError as e:
			if "invalid packet size" in str(e) or "query timed out" in str(e):
				self.dataset.update_status(
					"Error during query. Your query matches too many items. Try again with a narrower date range or a more specific search query.",
					is_final=True)
			elif "syntax error" in str(e):
				self.dataset.update_status(
					"Error during query. Your query syntax may be invalid (check for loose parentheses).",
					is_final=True)
			else:
				self.dataset.update_status(
					"Error during query. Please try a narrow query and double-check your syntax.", is_final=True)
				self.log.error("Sphinx crash during query %s: %s" % (self.dataset.key, e))
			return None


		self.log.info("Sphinx query finished in %i seconds, %i results." % (time.time() - sphinx_start, len(results)))
		return results

	def get_sphinx_handler(self):
		"""
		Get a MySQL database object that can be used to interact with Sphinx

		:return MySQLDatabase:
		"""
		return MySQLDatabase(
			host="localhost",
			user=config.DB_USER,
			password=config.DB_PASSWORD,
			port=9306,
			logger=self.log
		)

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

	def validate_query(query, request, user):
		"""
		Validate input for a dataset query on the 4chan data source.

		Will raise a QueryParametersException if invalid parameters are
		encountered. Mutually exclusive parameters may also be sanitised by
		ignoring either of the mutually exclusive options.

		:param dict query:  Query parameters, from client-side.
		:param request:  Flask request
		:param User user:  User object of user who has submitted the query
		:return dict:  Safe query parameters
		"""

		# this is the bare minimum, else we can't narrow down the full data set
		if not user.is_admin() and not user.get_value("4chan.can_query_without_keyword", False) and not query.get("body_match", None) and not query.get("subject_match", None) and query.get("search_scope",	"") != "random-sample":
			raise QueryParametersException("Please provide a message or subject search query")

		query["min_date"], query["max_date"] = query["daterange"]

		del query["daterange"]
		if query.get("search_scope") not in ("dense-threads",):
			del query["scope_density"]
			del query["scope_length"]

		if query.get("search_scope") not in ("match-ids",) and "valid_ids" in query.keys():
			del query["valid_ids"]

		return query

	def request_interrupt(self, level=1):
		"""
		Request an abort of this worker

		This is implemented in the basic worker class, and that method is
		called, but this additionally kills any running Sphinx queries because
		they are blocking, and will prevent the worker from actually stopping
		unless killed.

		:param int level:  Retry or cancel? Either `self.INTERRUPT_RETRY` or
		`self.INTERRUPT_CANCEL`.
		"""
		super(Search4Chan, self).request_interrupt(level)

		sphinx = self.get_sphinx_handler()
		threads = sphinx.fetchall("SHOW THREADS OPTION columns=5000")
		for thread in threads:
			if thread["Info"] == self.running_query:
				self.log.info("Killing Sphinx query %s" % thread["Tid"])
				sphinx.query("KILL %s" % thread["Tid"])
