import unittest
import requests
import json
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + '/../backend')
from workers.scrape_threads import ThreadScraper
from workers.scrape_boards import BoardScraper


class TestAPIConnection(unittest.TestCase):
	thread = None

	def get_thread(self):
		if self.thread is None:
			raw_json = requests.get("http://a.4cdn.org/tg/threads.json")
			data = json.loads(raw_json.content)

			page = data.pop()
			thread = page["threads"].pop()
			thread_id = thread["no"]

			raw_json = requests.get("http://a.4cdn.org/tg/thread/%i.json" % int(thread_id))
			self.thread = json.loads(raw_json.content)

		return self.thread

	def test_thread_index(self):
		"""
		Test if 4chan API response for boards has the correct format

		Expected: all fields marked as required in the board scraper are present
		"""
		raw_json = requests.get("http://a.4cdn.org/tg/threads.json")
		data = json.loads(raw_json.content)

		self.assertIsNotNone(data)
		self.assertGreater(len(data), 0)

		page = data.pop()
		self.assertTrue("page" in page)
		self.assertTrue("threads" in page)
		self.assertGreater(len(page["threads"]), 0)

		thread = page["threads"].pop()
		for field in BoardScraper.required_fields:
			with self.subTest(field=field):
				self.assertTrue(field in thread)

	def test_thread_single_required(self):
		"""
		Test if 4chan API response for individual threads has the correct format

		Expected: all fields marked as required in the thread scraper are present
		"""
		data = self.get_thread()
		self.assertTrue("posts" in data)

		post = data["posts"].pop()
		for field in ThreadScraper.required_fields:
			with self.subTest(field=field):
				self.assertTrue(field in post)

	def test_thread_single_known(self):
		"""
		Test if 4chan API response for individual threads has the correct format

		Expected: all fields in the response are marked as "known" in the thread scraper
		"""
		data = self.get_thread()
		self.assertTrue("posts" in data)

		post = data["posts"].pop()
		new = []
		for field in post:
			if field not in ThreadScraper.known_fields:
				new.append(field)

		explanation = ("\n\nThese fields are not currently recognized by 4CAT. If you think they"
					   "\nare significant, consider filing an issue about them on the 4CAT"
					   "\nGitHub repository so support for them can be added. 4CAT will still"
					   "\nwork even if this test (test_thread_single_known) fails!\n\nUnrecognized field(s): %s") % ", ".join(new)
		self.assertEqual(new, [], msg=explanation)
