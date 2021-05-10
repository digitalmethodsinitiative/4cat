"""
Usenet Search via Sphinx
"""
import time

from common.lib.helpers import UserInput
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException
from datasources.fourchan.search_4chan import Search4Chan


class SearchUsenet(Search4Chan):
	"""
	Search Usenet corpus

	Defines methods that are used to query the Usenet data indexed and saved.
	"""
	type = "usenet-search"  # job ID
	sphinx_index = "usenet"  # prefix for sphinx indexes for this data source. Should usually match sphinx.conf
	prefix = "usenet"  # table identifier for this datasource; see below for usage

	# Columns to return in csv
	return_cols = ['thread_id', 'id', 'timestamp', 'body', 'subject', 'author', 'groups', 'headers']

	# before running a sphinx query, store it here so it can be cancelled via
	# request_abort() later
	running_query = ""

	options = {
		"intro": {
			"type": UserInput.OPTION_INFO,
			"help": "Be sure to read the [query syntax](/page/query-syntax/) for local data sources first - your "
					"query design will significantly impact the results. Note that large queries can take a long time "
					"to complete!"
		},
		"body_match": {
			"type": UserInput.OPTION_TEXT,
			"help": "Message contains"
		},
		"subject_match": {
			"type": UserInput.OPTION_TEXT,
			"help": "Subject contains"
		},
		"group-help": {
			"type": UserInput.OPTION_INFO,
			"help": "You can enter multiple newsgroups, separate with commas. Trailing wildcards can be used to "
					"select all posts in a given hierarchy (e.g. `alt.fan.*`)."
		},
		"group_match": {
			"type": UserInput.OPTION_TEXT,
			"help": "Newsgroup(s)"
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
				"posts-only": "All matching messages",
				"full-threads": "All messages in threads with matching messages (full threads)",
				"dense-threads": "All messages in threads in which at least x% of messages match (dense threads)"
			},
			"default": "posts-only"
		},
		"scope_density": {
			"type": UserInput.OPTION_TEXT,
			"help": "Min. density %",
			"min": 0,
			"max": 100,
			"default": 15,
			"tooltip": "At least this many % of messages in the thread must match the query"
		},
		"scope_length": {
			"type": UserInput.OPTION_TEXT,
			"help": "Min. dense thread length",
			"min": 30,
			"default": 30,
			"tooltip": "A thread must at least be this many messages long to qualify as a 'dense thread'"
		}
	}

	def get_items_simple(self, query):
		"""
		Fast-lane for simpler queries that don't need the intermediate step
		where Sphinx is queried

		In practice this means queries that only select by time period
		:param query:
		:return:
		"""
		where = []
		replacements = []

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

		sql_query = ("SELECT p.* " \
					 "FROM posts_" + self.prefix + " AS p " \
					 "WHERE 1 ")

		if where:
			sql_query += " AND " + " AND ".join(where)

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

		# escape full text matches and convert quotes
		if query.get("body_match", None):
			match.append("@body " + self.convert_for_sphinx(query["body_match"]))

		if query.get("subject_match", None):
			match.append("@subject " + self.convert_for_sphinx(query["subject_match"]))

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

		groups = [group.strip().replace("*", "%") for group in query.get("group_match", "").split(",")]
		groups = [group for group in groups if group]
		posts_full = self.fetch_posts(tuple([post["post_id"] for post in posts]), postgres_where, postgres_replacements, groups)

		self.dataset.update_status("Post data collected")
		self.log.info("Full posts query finished in %i seconds." % (time.time() - datafetch_start))

		return posts_full

	def fetch_posts(self, post_ids, where=None, replacements=None, groups=None):
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

		if groups:
			where.append("id IN ( SELECT post_id FROM groups_" + self.prefix + " WHERE \"group\" LIKE ANY(%s) )")
			replacements.append(groups)

		query = "SELECT " + columns + " FROM posts_" + self.prefix + " WHERE " + " AND ".join(
			where) + " ORDER BY id ASC"
		return self.db.fetchall_interruptable(self.queue, query, replacements)

	def validate_query(query, request, user):
		"""
		Validate input for a dataset query on the Usenet data source.

		Will raise a QueryParametersException if invalid parameters are
		encountered. Mutually exclusive parameters may also be sanitised by
		ignoring either of the mutually exclusive options.

		:param dict query:  Query parameters, from client-side.
		:param request:  Flask request
		:param User user:  User object of user who has submitted the query
		:return dict:  Safe query parameters
		"""

		# this is the bare minimum, else we can't narrow down the full data set
		if not user.is_admin() and not user.get_value("usenet.can_query_without_keyword", False) and not query.get("body_match", None) and not query.get("subject_match", None) and query.get("search_scope",	"") != "random-sample":
			raise QueryParametersException("Please provide a body query, subject query or random sample size.")

		# the dates need to make sense as a range to search within
		query["min_date"], query["max_date"] = query.get("daterange")
		if any(query.get("daterange")) and not all(query.get("daterange")):
			raise QueryParametersException("When providing a date range, set both an upper and lower limit.")

		del query["daterange"]

		# if we made it this far, the query can be executed
		return query
