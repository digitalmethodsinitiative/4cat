"""
Database wrapper
"""
import itertools
import psycopg2.extras
import psycopg2
import time

from psycopg2 import sql
from psycopg2.extras import execute_values

from common.lib.exceptions import DatabaseQueryInterruptedException


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
	appname=""

	interrupted = False
	interruptable_timeout = 86400  # if a query takes this long, it should be cancelled. see also fetchall_interruptable()
	interruptable_job = None

	def __init__(self, logger, dbname=None, user=None, password=None, host=None, port=None, appname=None):
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

		self.appname = "4CAT" if not appname else "4CAT-%s" % appname

		self.connection = psycopg2.connect(dbname=dbname, user=user, password=password, host=host, port=port, application_name=self.appname)
		self.cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
		self.log = logger


		if self.log is None:
			raise NotImplementedError

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

		self.log.debug("Executing query %s" % self.cursor.mogrify(query, replacements))

		return cursor.execute(query, replacements)

	def execute(self, query, replacements=None):
		"""
		Execute a query, and commit afterwards

		This is required for UPDATE/INSERT/DELETE/etc to stick
		:param string query:  Query
		:param replacements: Replacement values
		"""
		cursor = self.get_cursor()

		self.log.debug("Executing query %s" % self.cursor.mogrify(query, replacements))
		cursor.execute(query, replacements)
		self.commit()

		cursor.close()

	def execute_many(self, query, commit=True, replacements=None):
		"""
		Execute a query multiple times, each time with different values

		This makes it particularly suitable for INSERT queries, but other types
		of query using VALUES are possible too.

		:param string query:  Query
		:param replacements: A list of replacement values
		:param commit:  Commit transaction after query?
		"""
		cursor = self.get_cursor()
		execute_values(cursor, query, replacements)
		cursor.close()
		if commit:
			self.commit()

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

		if commit:
			self.commit()

		result = cursor.rowcount
		cursor.close()
		return result

	def delete(self, table, where, commit=True):
		"""
		Delete a database record

		:param string table:  Table to delete from
		:param dict where:  Simple conditions, parsed as "column1 = value1 AND column2 = value2" etc
		:param bool commit:  Whether to commit after executing the query

		:return int: Number of affected rows. Note that this may be unreliable if `commit` is `False`
		"""
		where_sql = []
		replacements = []
		for column in where.keys():
			if type(where[column]) in (set, tuple, list):
				where_sql.append("{} IN %s")
				replacements.append(tuple(where[column]))
			else:
				where_sql.append("{} = %s")
				replacements.append(where[column])

		# build query
		identifiers = [sql.Identifier(column) for column in where.keys()]
		identifiers.insert(0, sql.Identifier(table))
		query = sql.SQL("DELETE FROM {} WHERE " + " AND ".join(where_sql)).format(*identifiers)

		cursor = self.get_cursor()
		self.log.debug("Executing query: %s" % cursor.mogrify(query, replacements))
		cursor.execute(query, replacements)

		if commit:
			self.commit()

		result = cursor.rowcount
		cursor.close()
		return result

	def insert(self, table, data, commit=True, safe=False, constraints=None, return_field=""):
		"""
		Create database record

		:param string table:  Table to insert record into
		:param dict data:   Data to insert
		:param bool commit: Whether to commit after executing the query
		:param bool safe: If set to `True`, "ON CONFLICT DO NOTHING" is added to the insert query, so it does not
						  insert the row and no error is thrown when the insert violates a unique index or other constraint
		:param tuple constraints: If `safe` is `True`, this tuple may contain the columns that should be used as a
								  constraint, e.g. ON CONFLICT (name, lastname) DO NOTHING
		:param str return_field: If not empty or None, this makes the method
		return this field of the inserted row, instead of the number of
		affected rows, with `RETURNING`.
		:return int: Number of affected rows. Note that this may be unreliable if `commit` is `False`
		"""
		if constraints is None:
			constraints = []

		# escape identifiers
		identifiers = [sql.Identifier(column) for column in data.keys()]
		identifiers.insert(0, sql.Identifier(table))

		# construct ON NOTHING bit of query
		if safe:
			safe_bit = " ON CONFLICT "
			if constraints:
				safe_bit += "(" + ", ".join(["{}" for each in constraints]) + ")"
				identifiers.extend([sql.Identifier(column) for column in constraints])
			safe_bit += " DO NOTHING"
		else:
			safe_bit = ""

		# prepare parameter replacements
		protoquery = "INSERT INTO {} (%s) VALUES %%s" % ", ".join(["{}" for column in data.keys()]) + safe_bit

		if return_field:
			protoquery += " RETURNING {}"
			identifiers.append(sql.Identifier(return_field))

		query = sql.SQL(protoquery).format(*identifiers)
		replacements = (tuple(data.values()),)

		cursor = self.get_cursor()
		self.log.debug("Executing query: %s" % cursor.mogrify(query, replacements))
		cursor.execute(query, replacements)

		if commit:
			self.commit()

		result = cursor.rowcount if not return_field else cursor.fetchone()[return_field]
		cursor.close()
		return result

	def upsert(self, table, data, commit=True, constraints=None):
		"""
		Create or update database record

		If the record could not be inserted because of a constraint, the
		constraining record is updated instead.

		:param string table:  Table to upsert record into
		:param dict data:   Data to upsert
		:param bool commit: Whether to commit afxter executing the query
		:param tuple constraints: This tuple may contain the columns that should be used as a
								  constraint, e.g. ON CONFLICT (name, lastname) DO UPDATE
		:return int: Number of affected rows. Note that this may be unreliable if `commit` is `False`
		"""
		if constraints is None:
			constraints = []

		# escape identifiers
		identifiers = [sql.Identifier(column) for column in data.keys()]
		identifiers.insert(0, sql.Identifier(table))

		# prepare parameter replacements
		protoquery = "INSERT INTO {} (%s) VALUES %%s" % ", ".join(["{}" for column in data.keys()])
		protoquery += " ON CONFLICT"

		if constraints:
			protoquery += "(" + ", ".join(["{}" for each in constraints]) + ")"
			identifiers.extend([sql.Identifier(column) for column in constraints])

		protoquery += " DO UPDATE SET "
		protoquery += ", ".join(["%s = EXCLUDED.%s" % (column, column) for column in data.keys()])
		identifiers.extend(list(itertools.chain.from_iterable([[column, column] for column in data.keys()])))

		query = sql.SQL(protoquery).format(*identifiers)
		replacements = (tuple(data.values()),)

		cursor = self.get_cursor()
		self.log.debug("Executing query: %s" % cursor.mogrify(query, replacements))
		cursor.execute(query, replacements)

		if commit:
			self.commit()

		result = cursor.rowcount
		cursor.close()
		return result

	def fetchall(self, query, *args):
		"""
		Fetch all rows for a query

		:param string query:  Query
		:param args: Replacement values
		:param commit:  Commit transaction after query?
		:return list: The result rows, as a list
		"""
		cursor = self.get_cursor()
		self.log.debug("Executing query: %s" % cursor.mogrify(query, *args))
		self.query(query, cursor=cursor, *args)

		try:
			result = cursor.fetchall()
		except AttributeError:
			result = []

		cursor.close()
		self.commit()

		return result

	def fetchone(self, query, *args):
		"""
		Fetch one result row

		:param string query: Query
		:param args: Replacement values
		:param commit:  Commit transaction after query?
		:return: The row, as a dictionary, or None if there were no rows
		"""
		cursor = self.get_cursor()
		self.query(query, cursor=cursor, *args)

		try:
			result = cursor.fetchone()
		except psycopg2.ProgrammingError as e:
			# no results to fetch
			self.rollback()
			result = None

		cursor.close()
		self.commit()

		return result

	def fetchall_interruptable(self, queue, query, *args):
		"""
		Fetch all rows for a query, allowing for interruption

		Before running the query, a job is queued to cancel the query after a
		set amount of time. The query is expected to complete before this
		timeout. If the backend is interrupted, however, that job will be
		executed immediately, to cancel the database query. If this happens, a
		DatabaseQueryInterruptedException will be raised, but the database
		object will otherwise remain useable.

		Note that in the event that the cancellation job is run, all queries
		for this instance of the database object will be cancelled. However,
		there should never be more than one active query per connection within
		4CAT.

		:param JobQueue queue:  A job queue object, required to schedule the
		query cancellation job
		:param str query:  SQL query
		:param list args:  Replacement variables
		:param commit:  Commit transaction after query?
		:return list:  A list of rows, as dictionaries
		"""
		# schedule a job that will cancel the query we're about to make
		pid = self.connection.get_backend_pid()
		self.interruptable_job = queue.add_job("cancel-pg-query", details={}, remote_id=self.appname, claim_after=time.time() + self.interruptable_timeout)

		# make the query
		cursor = self.get_cursor()
		self.log.debug("Executing interruptable query: %s" % cursor.mogrify(query, *args))

		try:
			self.query(query, cursor=cursor, *args)
		except psycopg2.extensions.QueryCanceledError:
			# interrupted with cancellation worker (or manually)
			self.log.debug("Query in connection %s was interrupted..." % self.appname)
			self.rollback()
			cursor.close()
			raise DatabaseQueryInterruptedException("Interrupted while querying database")

		# collect results
		try:
			result = cursor.fetchall()
		except (AttributeError, psycopg2.ProgrammingError) as e:
			result = []

		# clean up cancelling job when we have the data
		self.interruptable_job.finish()
		self.interruptable_job = None

		cursor.close()
		self.commit()

		return result


	def commit(self):
		"""
		Commit the current transaction

		This is required for UPDATE etc to stick.
		"""
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

		Re-using cursors seems to give issues when using per-thread
		connections, so simply instantiate a new one each time

		:return: Cursor
		"""
		return self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
