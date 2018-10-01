import psycopg2
import psycopg2.extras

from psycopg2.extensions import AsIs

import config


class Database:
    """
    Simple database handler

    Most importantly, this sets up the database tables if they don't exist yet. Apart
    from that it offers a few wrapper methods for queries
    """
    connection = None
    cursor = None

    def __init__(self):
        """
        Set up database connection
        """
        self.connection = psycopg2.connect(dbname=config.db_name, user=config.db_user, password=config.db_password)
        self.cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

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

    def update(self, table, data, where={}, commit=True):
        """
        Update a database record

        :param string table:  Table to update
        :param dict where:  Simple conditions, parsed as "column1 = value1 AND column2 = value2" etc
        :param dict data:  Data to set, Column => Value
        :param bool commit:  Whether to commit after executing the query

        :return int: Number of affected rows. Note that this may be unreliable if `commit` is `False`
        """
        where_sql = ["%s = %%s" % column for column in where.keys()]
        replacements = list(where.values())

        set = ["%s = %%s" % column for column in data.keys()]
        [replacements.insert(0, value) for value in reversed(list(data.values()))]

        # build query
        query = "UPDATE " + table + " SET " + ", ".join(set)
        if len(where_sql) > 0:
            query += " WHERE " + " AND ".join(where_sql)
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
        where_sql = ["%s = %%s" % column for column in where.keys()]
        replacements = list(where.values())

        # build query
        query = "DELETE FROM " + table + " WHERE " + " AND ".join(where_sql)
        self.cursor.execute(query, replacements)

        if commit:
            self.commit()

        return self.cursor.rowcount

    def insert(self, table, data, commit=True):
        """
        Create database record

        :param string table:  Table to insert record into
        :param dict data:   Data to insert
        :param bool commit: Whether to commit after executing the query
        :return int: Number of affected rows. Note that this may be unreliable if `commit` is `False`
        """
        self.cursor.execute("INSERT INTO " + table + " (%s) VALUES %s",
                            (AsIs(", ".join(data.keys())), tuple(data.values())))

        if commit:
            self.commit()

        return self.cursor.rowcount

    def insert_or_update(self, table, data):
        """
        Create record, or update if already existing

        Either creates a record, or updates an existing record if a new one cannot be
        created because a table constraint is violated.

        :param string table:  Table to update/insert
        :param dict data:  Data, as a column => value dictionary

        :return int: Number of affected rows. Note that this may be unreliable if `commit` is `False`
        """
        set = ["%s = %%s" % column for column in data.keys()]
        replacements = list(data.values())

        replacements.insert(0, tuple(data.values()))
        replacements.insert(0, AsIs(", ".join(data.keys())))

        self.cursor.execute("INSERT INTO " + table + " (%s) VALUES %s ON CONFLICT DO UPDATE SET " + ", ".join(set),
                            replacements)
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

    def fetchone(self, query, replacements):
        """
        Fetch one result row

        :param query: Query
        :param replacements: Replacement values
        :return: The row, as a dictionary, or None if there were no rows
        """
        self.query(query, replacements)
        try:
            return self.cursor.fetchone()
        except AttributeError:
            return None

    def commit(self):
        """
        Commit the current transaction

        This is required for UPDATE etc to stick around.
        """
        self.connection.commit()
