import unittest
import os

import config
from backend.lib.logger import Logger
from backend.lib.database import Database


class FourcatTestCase(unittest.TestCase):
	db = None
	log = None
	root = ""

	example_record = {
		"jobtype": "test",
		"remote_id": "1234",
		"details": "",
		"claimed": 0,
		"claim_after": 0,
		"attempts": 0
	}

	@classmethod
	def setUpClass(cls):
		"""
		Set up database connection for test database before starting tests
		"""
		cls.root = os.path.abspath(os.path.dirname(__file__))
		cls.log = Logger(output=False)
		cls.db = Database(logger=cls.log, dbname=config.DB_NAME_TEST)
		with open(cls.root + "/../backend/database.sql") as dbfile:
			cls.db.execute(dbfile.read())

	@classmethod
	def tearDownClass(cls):
		"""
		Close database connection after tests are finished
		"""
		with open(cls.root + "/reset_database_tables.sql") as dbfile:
			cls.db.execute(dbfile.read())
		cls.db.close()
		del cls.db

	def setUp(self):
		"""
		Make sure there are no open transactions when a new test is loaded
		"""
		self.db.rollback()

	def tearDown(self):
		"""
		Reset database after each test
		"""
		self.db.rollback()
		with open(self.root + "/reset_database_content.sql") as dbfile:
			self.db.execute(dbfile.read())
