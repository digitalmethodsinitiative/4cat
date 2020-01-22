"""
Database wrapper
"""
import psycopg2.extras
import psycopg2
import select
import time

from psycopg2 import sql
from psycopg2.extras import execute_values
from psycopg2.extensions import POLL_OK, POLL_READ, POLL_WRITE

from backend.lib.exceptions import DatabaseQueryInterruptedException


import config


class Database:
	"""
	Simple database handler

	Offers a number of abstraction methods that limit how much SQL one is
	required to write. Also makes the database connection mostly multithreading
	proof by instantiating a new cursor for each query (and closing it afterwards)
	"""
	cursor = None
	log = None
	is_async = False

	interrupted = False
	interruptable_timeout = 86400  # if a query takes this long, it should be cancelled. see also fetchall_interruptable()
	interruptable_job = None

	def __init__(self, logger, dbname=None, user=None, password=None, host=None, port=None, appname=None, is_async=False):
		"""
		Set up database connection

		:param logger:  Logger instance
		:param dbname:  Database name
		:param user:  Database username
		:param password:  Database password
		:param host:  Database server address
		:param port:  Database port
		:param appname:  App name, mostly useful to trace connections in pg_stat_activity
		"""
		dbname = config.DB_NAME if not dbname else dbname
		user = config.DB_USER if not user else user
		password = config.DB_PASSWORD if not password else password
		host = config.DB_HOST if not host else host
		port = config.DB_PORT if not port else port

		appname = "4CAT" if not appname else "4CAT-%s" % appname

		self.connection = psycopg2.connect(async_=is_async, dbname=dbname, user=user, password=password, host=host, port=port, application_name=appname)
		self.is_async = is_async
		if is_async:
			self.wait_for_connection()

		self.cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
		self.log = logger


		if self.log is None:
			raise NotImplementedError

		self.setup()

	def setup(self):
		"""
		This used to do something, but now it doesn't really
		"""
		if not self.is_async:
			self.commit()

	def query(self, query, replacements=None, cursor=None):
		"""
		Execute a query

		:param string query: Query
		:param args: Replacement values
		:param cursor: Cursor to use. Default - use common cursor
		:return None:
		"""
		if not cursor:
			cursor = self.get_cursor()

		if self.is_async:
			self.wait_for_connection()

		self.log.debug("Executing query %s" % self.cursor.mogrify(query, replacements))

		return cursor.execute(query, replacements)

	def execute(self, query, replacements=None, cursor=None):
		"""
		Execute a query, and commit afterwards

		This is required for UPDATE/INSERT/DELETE/etc to stick
		:param string query:  Query
		:param replacements: Replacement values
		:param cursor: Cursor to use. Default - use common cursor
		"""
		if not cursor:
			cursor = self.get_cursor()

		if self.is_async:
			self.wait_for_connection()


		self.log.debug("Executing query %s" % self.cursor.mogrify(query, replacements))
		cursor.execute(query, replacements)

		if not self.is_async:
			self.commit()

	def execute_many(self, query, replacements=None, cursor=None):
		"""
		Execute a query multiple times, each time with different values

		This makes it particularly suitable for INSERT queries, but other types
		of query using VALUES are possible too.

		:param string query:  Query
		:param replacements: A list of replacement values
		:param cursor: Cursor to use. Default - use common cursor
		"""
		if not cursor:
			cursor = self.get_cursor()

		if self.is_async:
			self.wait_for_connection()

		execute_values(cursor, query, replacements)

	def update(self, table, data, where=None, commit=True):
		"""
		Update a database record

		:param string table:  Table to update
		:param dict where:  Simple conditions, parsed as "column1 = value1 AND column2 = value2" etc
		:param dict data:  Data to set, Column => Value
		:param bool commit:  Whether to commit after executing the query

		:return int: Number of affected rows. Note that this may be unreliable if `commit` is `False`
		"""
		if where is None:
			where = {}

		if self.is_async:
			self.wait_for_connection()

		# build query
		identifiers = [sql.Identifier(column) for column in data.keys()]
		identifiers.insert(0, sql.Identifier(table))
		replacements = list(data.values())

		query = "UPDATE {} SET " + ", ".join(["{} = %s" for column in data])
		if where:
			query += " WHERE " + " AND ".join(["{} = %s" for column in where])
			for column in where.keys():
				identifiers.append(sql.Identifier(column))
				replacements.append(where[column])

		query = sql.SQL(query).format(*identifiers)

		cursor = self.get_cursor()
		self.log.debug("Executing query: %s" % cursor.mogrify(query, replacements))
		cursor.execute(query, replacements)

		if commit and not self.is_async:
			self.commit()

		return cursor.rowcount

	def delete(self, table, where, commit=True):
		"""
		Delete a database record

		:param string table:  Table to delete from
		:param dict where:  Simple conditions, parsed as "column1 = value1 AND column2 = value2" etc
		:param bool commit:  Whether to commit after executing the query

		:return int: Number of affected rows. Note that this may be unreliable if `commit` is `False`
		"""
		if self.is_async:
			self.wait_for_connection()

		where_sql = ["{} = %s" for column in where.keys()]
		replacements = list(where.values())

		# build query
		identifiers = [sql.Identifier(column) for column in where.keys()]
		identifiers.insert(0, sql.Identifier(table))
		query = sql.SQL("DELETE FROM {} WHERE " + " AND ".join(where_sql)).format(*identifiers)

		cursor = self.get_cursor()
		self.log.debug("Executing query: %s" % cursor.mogrify(query, replacements))
		cursor.execute(query, replacements)

		if commit and not self.is_async:
			self.commit()

		return cursor.rowcount

	def insert(self, table, data, commit=True, safe=False, constraints=None):
		"""
		Create database record

		:param string table:  Table to insert record into
		:param dict data:   Data to insert
		:param bool commit: Whether to commit after executing the query
		:param bool safe: If set to `True`, "ON CONFLICT DO NOTHING" is added to the insert query, so that no error is
						  thrown when the insert violates a unique index or other constraint
		:param tuple constraints: If `safe` is `True`, this tuple may contain the columns that should be used as a
								  constraint, e.g. ON CONFLICT (name, lastname) DO NOTHING
		:return int: Number of affected rows. Note that this may be unreliable if `commit` is `False`
		"""
		if constraints is None:
			constraints = []

		if self.is_async:
			self.wait_for_connection()

		# escape identifiers
		identifiers = [sql.Identifier(column) for column in data.keys()]
		identifiers.insert(0, sql.Identifier(table))

		# construct ON NOTHING bit of query
		if safe:
			safe_bit = " ON CONFLICT "
			if constraints:
				safe_bit += "(" + ", ".join(["{}" for each in constraints]) + ")"
				for column in constraints:
					identifiers.append(sql.Identifier(column))
			safe_bit += " DO NOTHING"
		else:
			safe_bit = ""

		# prepare parameter replacements
		protoquery = "INSERT INTO {} (%s) VALUES %%s" % ", ".join(["{}" for column in data.keys()]) + safe_bit
		query = sql.SQL(protoquery).format(*identifiers)
		replacements = (tuple(data.values()),)

		cursor = self.get_cursor()
		self.log.debug("Executing query: %s" % cursor.mogrify(query, replacements))
		cursor.execute(query, replacements)

		if commit and not self.is_async:
			self.commit()

		return cursor.rowcount

	def fetchall(self, query, *args):
		"""
		Fetch all rows for a query

		:param string query:  Query
		:param args: Replacement values
		:return list: The result rows, as a list
		"""
		if self.is_async:
			self.wait_for_connection()

		cursor = self.get_cursor()
		self.log.debug("Executing query: %s" % cursor.mogrify(query, *args))
		self.query(query, cursor=cursor, *args)

		if self.is_async:
			self.wait_for_connection()

		try:
			result = cursor.fetchall()
		except AttributeError:
			result = []

		return result

	def fetchone(self, query, *args):
		"""
		Fetch one result row

		:param string query: Query
		:param args: Replacement values
		:return: The row, as a dictionary, or None if there were no rows
		"""
		if self.is_async:
			self.wait_for_connection()

		cursor = self.get_cursor()
		self.query(query, cursor=cursor, *args)

		if self.is_async:
			self.wait_for_connection()

		try:
			result = cursor.fetchone()
		except psycopg2.ProgrammingError:
			# no results to fetch
			if not self.is_async:
				self.commit()
			result = None

		return result

	def fetchall_interruptable(self, queue, query, *args):
		"""
		Fetch all rows for a query, allowing for interruption

		Requires the database connection to be asynchronous (instantiate with
		`is_async` = `True`). Before running the query, a job is queued to
		cancel the query after a set amount of time. Usually the query
		completes before this timeout. If the backend is interrupted, however,
		the job can be executed immediately, to cancel the database query.

		:param JobQueue queue:  A job queue object, required to schedule the
		query cancellation job
		:param str query:  SQL query
		:param list args:  Replacement variables
		:return list:  A list of rows, as dictionaries
		"""
		if not self.is_async:
			raise RuntimeError("Interruptable queries may only be executed via an asynchronous Postgres connection")

		if self.interruptable_job:
			raise RuntimeError("You cannot run two queries at the same time on a single Postgres connection")

		# schedule a job that will cancel the query we're about to make
		pid = self.connection.get_backend_pid()
		self.wait_for_connection()
		self.interruptable_job = queue.add_job("cancel-pg-query", details={}, remote_id=pid, claim_after=time.time() + self.interruptable_timeout)

		# make the query
		self.wait_for_connection()
		cursor = self.get_cursor()
		self.log.debug("Executing interruptable query: %s" % cursor.mogrify(query, *args))
		self.query(query, cursor=cursor, *args)

		# collect results
		self.wait_for_connection()
		try:
			result = cursor.fetchall()
		except (AttributeError, psycopg2.ProgrammingError) as e:
			result = []

		# clean up cancelling job when we have the data
		self.wait_for_connection()
		self.interruptable_job.finish()
		self.interruptable_job = None

		return result

	def wait_for_connection(self):
		"""
		Loop until a query has finished

		Used for asynchronous queries
		"""
		poll_interval = 0.5  # poll every so often

		while True:
			try:
				# loop this until the query is done
				state = self.connection.poll()

				if state == POLL_OK:
					break
				elif state == POLL_READ:
					select.select([self.connection.fileno()], [], [], poll_interval)
				elif state == POLL_WRITE:
					select.select([], [self.connection.fileno()], [], poll_interval)
				else:
					raise self.connection.OperationalError("Bad state from postgres connection poll: %s" % state)
			except psycopg2.extensions.QueryCanceledError:
				# this happens if the query gets interrupted because of a backend shutdown
				# (or if someone manually does pg_cancel_backend()....)
				self.connection.cancel()
				raise DatabaseQueryInterruptedException


	def commit(self):
		"""
		Commit the current transaction

		This is required for UPDATE etc to stick.
		"""
		if self.is_async:
			raise RuntimeError("Cannot commit a transaction via an asynchronous Postgres connection")

		self.connection.commit()

	def rollback(self):
		"""
		Roll back the current transaction
		"""
		self.connection.rollback()

	def close(self):
		"""
		Close connection

		Running queries after this is probably a bad idea!
		"""
		self.connection.close()

	def get_cursor(self):
		"""
		Get a new cursor

		:return: Cursor
		"""
		if not self.cursor or self.cursor.closed:
			if self.is_async:
				self.wait_for_connection()
			self.cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

		return self.cursor
