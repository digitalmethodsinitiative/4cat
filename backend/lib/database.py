"""
Database wrapper
"""
import psycopg2.extras
import psycopg2
import sys
import os

from psycopg2 import sql

sys.path.insert(0, os.path.dirname(__file__) +  '/../..')
import config


class Database:
    """
    Simple database handler

    Most importantly, this sets up the database tables if they don't exist yet. Apart
    from that it offers a few wrapper methods for queries
    """
    cursor = None
    log = None

    def __init__(self, logger):
        """
        Set up database connection
        """
        self.connection = psycopg2.connect(dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD,
                                           host=config.DB_HOST, port=config.DB_PORT)
        self.cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        self.log = logger

        if self.log is None:
            raise NotImplementedError

        self.setup()

    def setup(self):
        """
        This used to do something, but now it doesn't really
        """
        self.commit()

    def query(self, query, replacements=None):
        """
        Execute a query

        :param string query: Query
        :param args: Replacement values
        :return None:
        """
        self.log.debug("Executing query %s" % self.cursor.mogrify(query, replacements))

        return self.cursor.execute(query, replacements)

    def execute(self, query, replacements=None):
        """
        Execute a query, and commit afterwards

        This is required for UPDATE/INSERT/DELETE/etc to stick
        :param string query:  Query
        :param replacements: Replacement values
        """
        self.cursor.execute(query, replacements)
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

        self.log.debug("Executing query: %s" % self.cursor.mogrify(query, replacements))
        self.cursor.execute(query, replacements)

        if commit:
            self.commit()

        return self.cursor.rowcount

    def delete(self, table, where, commit=True):
        """
        Delete a database record

        :param string table:  Table to delete from
        :param dict where:  Simple conditions, parsed as "column1 = value1 AND column2 = value2" etc
        :param bool commit:  Whether to commit after executing the query

        :return int: Number of affected rows. Note that this may be unreliable if `commit` is `False`
        """
        where_sql = ["{} = %s" for column in where.keys()]
        replacements = list(where.values())

        # build query
        identifiers = [sql.Identifier(column) for column in where.keys()]
        identifiers.insert(0, sql.Identifier(table))
        query = sql.SQL("DELETE FROM {} WHERE " + " AND ".join(where_sql)).format(*identifiers)

        self.log.debug("Executing query: %s" % self.cursor.mogrify(query, replacements))
        self.cursor.execute(query, replacements)

        if commit:
            self.commit()

        return self.cursor.rowcount

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

        self.log.debug("Executing query: %s" % self.cursor.mogrify(query, replacements))
        self.cursor.execute(query, replacements)

        if commit:
            self.commit()

        return self.cursor.rowcount

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
        except psycopg2.ProgrammingError:
            self.commit()
            return None

    def commit(self):
        """
        Commit the current transaction

        This is required for UPDATE etc to stick around.
        """
        self.connection.commit()

    def close(self):
        """
        Close connection

        Running queries after this is probably a bad idea!
        """
        self.connection.close()
