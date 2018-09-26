import psycopg2
import psycopg2.extras

from config import config


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
        Create, if they don't exist yet, the tables and indexes required for the scraper to work.
        """
        # create jobtype type
        self.execute("""
        DO $$ BEGIN
            CREATE TYPE jobtype AS ENUM ('board', 'thread', 'search', 'misc');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$
        """)

        # create job table
        self.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id SERIAL PRIMARY KEY,
            jobtype jobtype DEFAULT 'misc',
            remote_id text,
            details text,
            owner text,
            timestamp integer,
            claimed integer DEFAULT 0
        );
        """)

        # make sure there is only ever one job for any one item of a given type  (this hangs psycopg2 somehow...?)
        # self.execute("""
        # CREATE UNIQUE INDEX IF NOT EXISTS unique_job ON jobs (
        #    jobtype,
        #    remote_id
        # );
        # """)

        # create posts table
        self.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id integer PRIMARY KEY,
            post text
        );
        """)

        self.commit()

    def execute(self, query, *args):
        """
        Execute a query

        :param string query: Query
        :param args: Replacement values
        :return None:
        """
        return self.cursor.execute(query, *args)

    def update(self, query, *args):
        """
        Execute a query, and commit afterwards

        This is required for UPDATE/INSERT/DELETE/etc to stick
        :param string query:  Query
        :param args: Replacement values
        """
        self.cursor.execute(query, *args)
        self.commit()

    def fetchall(self, query, *args):
        """
        Fetch all rows for a query
        :param query:  Query
        :param args: Replacement values
        :return list: The result rows, as a list
        """
        self.execute(query, *args)
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
        self.execute(query, *args)
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
