import unittest
import json
import os

from test.basic_testcase import FourcatTestCase
from backend.lib.query import SearchQuery


class TestQuery(FourcatTestCase):
	"""
	Test the SearchQuery class
	"""
	default_parameters = {"before": 1540477901, "after": 0}
	default_key = "291391f1636c710e00f9a136e54d770a"

	def test_create_key(self):
		"""
		Test creating a unique key for a query

		Expected: the key is the expected MD5 Hash
		"""
		query = SearchQuery(query="obama", parameters=self.default_parameters, db=self.db)
		self.assertEqual(query.key, self.default_key)

	def test_create_query(self):
		"""
		Test creating a query

		Expected: data is properly inserted into database
		"""
		SearchQuery(query="obama", parameters=self.default_parameters, db=self.db)

		result = self.db.fetchone("SELECT * FROM queries")
		self.assertIsNotNone(result)

		expected = {
			"key": self.default_key,
			"query": "obama",
			"parameters": json.dumps(self.default_parameters),
			"is_finished": False
		}

		for key in expected:
			with self.subTest(key=key):
				self.assertEqual(expected[key], result[key])

	def test_key_not_match_query(self):
		"""
		Test if hash changes if query changes

		Expected: hash changes
		"""
		query = SearchQuery(query="trump", parameters=self.default_parameters, db=self.db)
		self.assertNotEqual(query.key, self.default_key)

	def test_key_not_match_parameters(self):
		"""
		Test if hash changes if parameters change

		Expected: hash changes
		"""
		query = SearchQuery(query="trump", parameters={"president": True}, db=self.db)
		self.assertNotEqual(query.key, self.default_key)

	def test_reserve_file(self):
		"""
		Test reserving a query's result file

		Expected:
		"""
		query = SearchQuery(query="obama", parameters=self.default_parameters, db=self.db)

		with self.subTest("Result path is reserved"):
			self.assertNotEqual("", query.data["result_file"])
			path = query.get_results_path()
			self.assertFalse(os.path.isfile(path))

		with self.subTest("Result path available after finishing"):
			touch = open(query.get_results_path(), "w")
			touch.close()
			query.finish()

			self.assertIsNotNone(query.get_results_path())

		os.unlink(query.get_results_path())

	def test_state(self):
		"""
		Test performing preparation methods on a finished query

		Expected: RuntimeErrors are raised
		"""
		query = SearchQuery(query="obama", parameters=self.default_parameters, db=self.db)
		query.finish()

		with self.subTest("Reserving a finished query's result file"):
			with self.assertRaises(RuntimeError):
				query.reserve_result_file()

		with self.subTest("Finishing a finished query"):
			with self.assertRaises(RuntimeError):
				query.finish()

	def test_instantiate_key(self):
		"""
		Test instantiating a SearchQuery by key

		Expected: the same record is used in both cases
		"""
		query = SearchQuery(query="obama", parameters=self.default_parameters, db=self.db)
		other_query = SearchQuery(key=self.default_key, db=self.db)

		self.assertEqual(other_query.data["query"], "obama")
		self.assertEqual(query.key, other_query.key)

	def test_instantiate_queryparam(self):
		"""
		Test instantiating a SearchQuery by query/param combination

		Expected: the same record is used in both cases
		"""
		query = SearchQuery(query="obama", parameters=self.default_parameters, db=self.db)
		other_query = SearchQuery(query="obama", parameters=self.default_parameters, db=self.db)

		self.assertEqual(query.key, other_query.key)

		amount = self.db.fetchone("SELECT COUNT(*) AS num FROM queries")["num"]
		self.assertEqual(amount, 1)

	def test_instantiate_key_fail(self):
		"""
		Test instantiating a search query with a non-existent key

		Expected: a TypeError is raised
		"""
		with self.assertRaises(TypeError):
			SearchQuery(key="fake-key", db=self.db)

	def test_status(self):
		query = SearchQuery(query="obama", parameters=self.default_parameters, db=self.db)

		self.assertEqual(query.get_status(), "")
		query.update_status("test 1")
		self.assertEqual(query.get_status(), "test 1")
		query.update_status("test 2")
		self.assertEqual(query.get_status(), "test 2")

	def test_instantiate_queryparam_fail(self):
		"""
		Test instantiating a search query with a lack of parameters

		Expected: a TypeError is raised
		"""
		with self.assertRaises(TypeError):
			SearchQuery(query="", db=self.db)


if __name__ == '__main__':
	unittest.main()
