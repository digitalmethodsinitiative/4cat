"""
Database wrapper
"""
import pymysql.connections as mysqlconnections
import pymysql

import config


class MySQLDatabase:
	"""
	Simple database handler for MySQL connections

	4CAT uses PostgreSQL for its database - this MySQL class is available as a
	convenience for data sources that wish to use the Sphinx full-text search
	engine via SphinxQL. As such, only methods needed for that (i.e.
	`fetchall()`) are implemented.
	"""
	cursor = None
	log = None

	def __init__(self, logger, dbname=None, user=None, password=None, host=None, port=None):
		"""
		Set up database connection
		"""
		dbname = config.DB_NAME if not dbname else dbname
		user = config.DB_USER if not user else user
		password = config.DB_PASSWORD if not password else password
		host = config.DB_HOST if not host else host
		port = config.DB_PORT if not port else port

		self.connection = mysqlconnections.Connection(database=dbname, user=user, password=password, host=host, port=port)
		self.cursor = self.connection.cursor(pymysql.cursors.DictCursor)
		self.log = logger

		if self.log is None:
			raise NotImplementedError

	def mogrify(self, query, replacements):
		"""
		Parse a query with replacement variables

		:param str query:  Query
		:param list replacements:  Replacement variables
		:return str: Parsed query
		"""
		return self.cursor.mogrify(query, replacements)

	def query(self, query, replacements=None):
		"""
		Execute a query

		:param string query: Query
		:param args: Replacement values
		:return None:
		"""
		self.log.debug("Executing query %s" % self.mogrify(query, replacements))

		return self.cursor.execute(query, replacements)

	def fetchall(self, query, *args):
		"""
		Fetch all rows for a query
		:param query:  Query
		:param args: Replacement values
		:return list: The result rows, as a list
		"""
		self.query(query, *args)
		try:
			return self.cursor.fetchall()
		except AttributeError:
			return []

	def fetchone(self, query, *args):
		"""
		Fetch one result row

		:param query: Query
		:param args: Replacement values
		:return: The row, as a dictionary, or None if there were no rows
		"""
		self.query(query, *args)
		try:
			return self.cursor.fetchone()
		except pymysql.ProgrammingError:
			self.commit()
			return None

	def commit(self):
		"""
		Commit the current transaction

		This is required for UPDATE etc to stick around.
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
