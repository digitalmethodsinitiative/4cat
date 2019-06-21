import requests
import unittest
import json
import time

from test.basic_testcase import FourcatTestCase
from backend.lib.dataset import DataSet

import config


class TestQuery(FourcatTestCase):
	"""
	Test queueing and manipulating queries via the web API
	"""

	def api_url(self, endpoint):
		"""
		Generate API URL for given endpoint

		:param endpoint:  Endpoint to generate URL for
		:return:  Endpoint URL
		"""
		return "http://" + config.FlaskConfig.SERVER_NAME + "/api/" + endpoint + "/"

	def get_api(self, endpoint, data=None, is_json=True, post=False):
		"""
		Call API via GET request

		:param endpoint:  Endpoint to call
		:param data:  Data to send
		:param is_json:  Interpret result as json?
		:param post:  Send as POST request?
		:return: Response
		"""
		time.sleep(1)  # avoid rate-limiting
		url = self.api_url(endpoint)
		if post:
			content = requests.post(url, headers={"Authorization": self.token}, data=data).content
		else:
			content = requests.get(url, headers={"Authorization": self.token}, params=data).content

		if is_json:
			try:
				response = json.loads(content)
				return response
			except json.JSONDecodeError:
				raise Exception("For %s: %s" % (url, content))
		else:
			return content

	def post_api(self, endpoint, data=None, is_json=True):
		"""
		Call API via POST

		:param endpoint:  Endpoint to call
		:param data:  Data to send
		:param is_json:  Interpret result as JSON?
		:return:  Response
		"""
		return self.get_api(endpoint, data, is_json, post=True)

	def setUp(self):
		"""
		Load queryable platforms and boards from config, and create a temporary
		user with an API access code
		"""
		super().setUp()
		if config.FlaskConfig.DEBUG != "Test":
			self.skipTest("Web app is not in Test mode. Set config.FlaskConfig.DEBUG to 'Test' to test the API.")

		if not config.PLATFORMS:
			self.skipTest("No platforms available")

		self.platform = list(config.PLATFORMS.keys())[0]

		if not config.PLATFORMS[self.platform]["boards"]:
			self.skipTest("No boards available for platform %s" % self.platform)

		# get token
		self.db.insert("users", data={"name": "UNIT_TEST", "password": ""}, safe=True)
		self.db.insert("access_tokens", data={"name": "UNIT_TEST", "token": "UNIT_TEST"}, safe=True)
		self.token = "UNIT_TEST"

		self.board = config.PLATFORMS[self.platform]["boards"][0]

	def tearDown(self):
		"""
		Remove temporary user and access token
		"""
		super().tearDown()
		self.db.delete("users", where={"name": "UNIT_TEST"})
		self.db.delete("access_tokens", where={"name": "UNIT_TEST"})

	def test_queue_query(self):
		"""
		Test queueing a query via the API
		"""

		querydata = {
			"board": self.board,
			"platform": self.platform,
			"body_query": "BODY_TEST",
			"subject_query": "SUBJECT_TEST",
			"full_thread": "yes",
			"dense_threads": "yes",
			"use_date": "yes",
			"dense_percentage": 20,
			"dense_length": 20,
			"min_date": "01-01-2016",
			"max_date": "01-03-2016"
		}

		key = self.post_api("queue-query", data=querydata, is_json=False).decode("utf-8")
		query = DataSet(key=key, db=self.db)

		# check if the query was added to the database correctly
		del querydata["use_date"]
		for field in querydata:
			with self.subTest(field=field):
				if field in ("full_thread", "dense_threads"):
					self.assertEqual(True, query.parameters[field])
				elif field == "max_date":
					self.assertEqual(str(query.parameters[field]), "1456786800")
				elif field == "min_date":
					self.assertEqual(str(query.parameters[field]), "1451602800")
				else:
					self.assertEqual(str(querydata[field]), str(query.parameters[field]))

	def test_check_query(self):
		"""
		Check if we can get the status of a queued query
		"""
		# queue a dummy query
		key = self.post_api("queue-query",
							data={"board": self.board, "platform": self.platform, "body_query": "UNIT_TEST"},
							is_json=False).decode("utf-8")
		status = self.get_api("check-query", data={"key": key})

		expected = {"status", "query", "rows", "key", "done", "preview", "path", "empty"}
		self.assertEqual(set(status.keys()), expected)

	def test_get_postprocessors(self):
		"""
		Check if post-processors may be retrieved
		"""
		# queue a dummy query
		key = self.post_api("queue-query",
							data={"board": self.board, "platform": self.platform, "body_query": "UNIT_TEST"},
							is_json=False).decode("utf-8")
		postprocessors = self.get_api("get-available-postprocessors", data={"key": key})

		# we don't know what postprocessors are available, but at least check if they
		# are available and with the right format
		with self.subTest("Result not empty"):
			self.assertGreater(len(postprocessors), 0)

		with self.subTest("Response format"):
			expected = {"type", "description", "name", "extension", "category", "accepts", "options"}
			for postprocessor in postprocessors.values():
				self.assertEqual(set(postprocessor.keys()), expected)

	def test_queue_postprocessor(self):
		"""
		Test queueing an analysis for a query
		"""
		# queue a dummy query
		key = self.post_api("queue-query",
							data={"board": self.board, "platform": self.platform, "body_query": "UNIT_TEST"},
							is_json=False).decode("utf-8")
		postprocessor = list(self.get_api("get-available-postprocessors", data={"key": key}).values())[0]
		settings = self.post_api("queue-postprocessor", data={"key": key, "postprocessor": postprocessor["type"]})

		expected = {"status", "container", "key", "html", "messages"}
		self.assertEqual(set(settings.keys()), expected)

	def test_check_postprocessor(self):
		"""
		Test checking the status of a queued analysis
		"""
		# queue a dummy query and post-processor
		key = self.post_api("queue-query",
							data={"board": self.board, "platform": self.platform, "body_query": "UNIT_TEST"},
							is_json=False).decode("utf-8")
		postprocessor = list(self.get_api("get-available-postprocessors", data={"key": key}).values())[0]
		settings = self.post_api("queue-postprocessor", data={"key": key, "postprocessor": postprocessor["type"]})

		check_params = {"subqueries": json.dumps([settings["key"]])}
		status = self.get_api("check-postprocessors", data=check_params)

		with self.subTest("Response not empty"):
			self.assertGreater(len(status), 0)

		with self.subTest("Response format"):
			expected = {"key", "finished", "html", "url"}
			self.assertEqual(set(status[0].keys()), expected)

	def test_check_invalid_query(self):
		"""
		Test failure on checking the status of a non-existent query
		"""
		response = self.get_api("check-query", data={"key": "UNIT_TEST"})
		self.assertIn("error", response)

	def test_get_postprocessors_for_invalid_query(self):
		"""
		Test failure on getting available post-processors for invalid query key
		"""
		response = self.get_api("get-available-postprocessors", data={"key": "UNIT_TEST"})
		self.assertIn("error", response)

	def test_check_invalid_postprocessor(self):
		"""
		Test failure on checking status of a non-existent post-processor
		"""
		response = self.get_api("check-postprocessors", data={"subqueries": "UNIT_TEST"})
		self.assertIn("error", response)


if __name__ == '__main__':
	unittest.main()
