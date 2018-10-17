import unittest
import json
import time
import sys
import re
import os

from basic_testcase import FourcatTestCase

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + '/../backend')
from workers.scrape_boards import BoardScraper


class TestBoardScraper(FourcatTestCase):
	job = {"remote_id": "test", "jobtype": "thread"}

	def load_board(self, filename):
		"""
		Loads a file as JSON data and provides a scraper to test it with

		:param filename:  JSON file to load
		:return tuple: (scraper, threaddata)
		"""
		with open(self.root + "/4chan_json/" + filename) as boardfile:
			board = boardfile.read()

		scraper = BoardScraper(db=self.db, logger=self.log)
		scraper.loop_time = int(time.time())
		boarddata = json.loads(board)

		return (scraper, boarddata)

	def test_thread_queue_threads(self):
		"""
		Test queueing threads based on scraped board data

		Expected: all items in the JSON are queued as thread scrapes with their associated data
		"""
		(scraper, boarddata) = self.load_board("board_valid.json")

		scraper.process(boarddata, self.job)

		jobs = self.db.fetchall("SELECT * FROM jobs WHERE jobtype = %s", ("thread",))
		with self.subTest("amount"):
			self.assertEqual(len(jobs), 30)

		for job in jobs:
			with self.subTest(job):
				with self.subTest(job=job, id="ID"):
					thread_id = int(job["remote_id"])
					self.assertGreater(thread_id, 0)
				with self.subTest(job=job, id="details"):
					details = json.loads(job["details"])
					self.assertTrue("board" in details)
					self.assertEqual(details["board"], "test")

	def test_thread_insert(self):
		"""
		Test saving thread data from import

		Expected: Data inserted for all threads and following the proper format
		"""
		(scraper, boarddata) = self.load_board("board_valid.json")

		scraper.process(boarddata, self.job)
		threads = self.db.fetchall("SELECT * FROM threads")
		history = int(time.time()) - 10

		index_regex = re.compile("((?:[0-9]+:[0-9]+,))*")

		for thread in threads:
			with self.subTest(thread=thread):
				self.assertGreater(thread["timestamp_scraped"], history)

			with self.subTest(thread=thread):
				self.assertGreater(thread["timestamp_modified"], 0)

			with self.subTest(thread=thread):
				self.assertRegex(thread["index_positions"], index_regex)

	def test_thread_insert_invalid(self):
		"""
		Test saving thread data from an incomplete JSON file

		Expected: Threads with incomplete data are ignored
		"""
		(scraper, boarddata) = self.load_board("board_invalid_incomplete.json")

		scraper.process(boarddata, self.job)
		threads = self.db.fetchone("SELECT COUNT(*) AS num FROM threads")["num"]

		self.assertEqual(threads, 13)


if __name__ == '__main__':
	unittest.main()
