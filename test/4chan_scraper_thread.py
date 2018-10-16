import unittest
import json
import time
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + '/..')
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + '/../backend')
import config
from lib.helpers import get_absolute_folder
from lib.logger import Logger
from lib.database import Database
from workers.scrape_threads import ThreadScraper


class TestThreadScraper(unittest.TestCase):
	db = None
	job = {"details": {"board": "test"}, "remote_id": -1, "jobtype": "thread"}

	@classmethod
	def setUpClass(cls):
		"""
		Set up database connection for test database before starting tests
		"""
		cls.log = Logger(output=False)
		cls.db = Database(logger=cls.log, dbname=config.DB_NAME_TEST)
		with open("../backend/database.sql") as dbfile:
			cls.db.execute(dbfile.read())

	@classmethod
	def tearDownClass(cls):
		"""
		Close database connection after tests are finished
		"""
		cls.db.close()
		del cls.db

	def tearDown(self):
		"""
		Reset database after each test
		"""
		with open("reset_database.sql") as dbfile:
			self.db.execute(dbfile.read())

	def load_thread(self, filename):
		"""
		Loads a file as JSON data and provides a scraper to test it with

		:param filename:  JSON file to load
		:return tuple: (scraper, threaddata)
		"""
		with open(filename) as threadfile:
			thread = threadfile.read()

		scraper = ThreadScraper(db=self.db, logger=self.log)
		scraper.loop_time = int(time.time())
		threaddata = json.loads(thread)

		return (scraper, threaddata)

	def test_process_thread_valid(self):
		"""
		Test processing of a valid thread JSON

		Expected: six posts are imported
		"""
		(scraper, threaddata) = self.load_thread("4chan_json/thread_valid.json")

		processed = scraper.process(threaddata, job=self.job)
		self.assertEqual(processed, 6)

	def test_process_thread_invalid(self):
		"""
		Test processing of a thread with an incomplete OP

		Expected: processing cannot complete
		"""
		(scraper, threaddata) = self.load_thread("4chan_json/thread_invalid_op.json")

		processed = scraper.process(threaddata, job=self.job)
		self.assertFalse(processed)

	def test_process_thread_incomplete(self):
		"""
		Test processing of a thread with a valid OP and a number of invalid posts, each post missing a different
		required field.

		Expected: only two posts are imported
		"""
		(scraper, threaddata) = self.load_thread("4chan_json/thread_invalid_posts.json")

		processed = scraper.process(threaddata, job=self.job)
		self.assertEqual(processed, 2)

	def test_process_thread_duplicate(self):
		"""
		Test processing of the same thread twice (i.e. duplicate posts)

		Expected: first one imports posts, second doesn't
		"""
		(scraper, threaddata) = self.load_thread("4chan_json/thread_valid.json")

		processed_first = scraper.process(threaddata, job=self.job)
		processed_second = scraper.process(threaddata, job=self.job)
		self.assertGreater(processed_first, 0)
		self.assertEqual(processed_second, 0)

	def test_unknown_fields(self):
		"""
		Test importing unknown data fields in post body
		"""
		(scraper, threaddata) = self.load_thread("4chan_json/thread_valid_unknownfields.json")

		scraper.process(threaddata, job=self.job)
		post = self.db.fetchone("SELECT * FROM posts")

		fields = json.loads(post["unsorted_data"])
		self.assertNotEqual(fields, None)
		self.assertEqual(fields, {"unknown1": "value1", "unknown2": "value2"})

	def test_known_fields_post(self):
		"""
		Test importing unknown data fields in post body
		"""
		(scraper, threaddata) = self.load_thread("4chan_json/thread_valid_onepost.json")
		threaddata["posts"] = threaddata["posts"][:1]

		scraper.process(threaddata, job=self.job)
		post = self.db.fetchone("SELECT * FROM posts")

		expected = {
			"id": 231108796,
			"thread_id": 231108796,
			"timestamp": 1539575674,
			"subject": "Heroes of the Storm General - \\/hotsg\\/",
			"body": "Infinity War Edition<br><br>New Players :<br><span class=\"quote\">&gt;Welcome to Heroes of the Storm!<\\/span><br>https:\\/\\/heroesofthestorm.com\\/en-us\\/<wbr>game\\/<br>https:\\/\\/youtu.be\\/wPk004vsjuE<br><br>News :<br><span class=\"quote\">&gt;A Message from Alan Dabiri<\\/span><br>https:\\/\\/us.forums.blizzard.com\\/en\\/h<wbr>eroes\\/t\\/a-message-from-alan-dabiri\\/<wbr>1761<br><br><span class=\"quote\">&gt;Malganis, Nathraziem Lord Confirmed<\\/span><br>https:\\/\\/heroesofthestorm.com\\/en-us\\/<wbr>heroes\\/malganis\\/<br>https:\\/\\/youtu.be\\/nd9aKlWu75k<br><br><span class=\"quote\">&gt;Fall of King&#039;s Crest Event<\\/span><br><span class=\"quote\">&gt;Haunting New Mounts, Banners, Sprays, and Portraits<\\/span><br><span class=\"quote\">&gt;Sept 25 - Oct 15<\\/span><br>https:\\/\\/bnetcmsus-a.akamaihd.net\\/cm<wbr>s\\/gallery\\/X4SV16SAU2KI1537806296438<wbr>.pdf<br>https:\\/\\/heroesofthestorm.com\\/en-us\\/<wbr>events\\/fall-of-kings-crest\\/<br>https:\\/\\/youtu.be\\/4nQSJovzkTo <br><br><span class=\"quote\">&gt;Kerrigan &amp; Brightwing Reworked<\\/span><br>https:\\/\\/youtu.be\\/7LJ7HqH4sNk <br>https:\\/\\/youtu.be\\/_pQNkqueMIE<br><br>E-Sports :<br><span class=\"quote\">&gt;HGC: Heroes Global Championship 2018<\\/span><br>https:\\/\\/esports.heroesofthestorm.co<wbr>m\\/en\\/<br><span class=\"quote\">&gt;Where can I watch?<\\/span><br>Blizzheroes @ Twitch<br><br>Resources :<br>https:\\/\\/pastebin.com\\/cX8QN3sm<br>https:\\/\\/heroespatchnotes.com\\/<br><br>Community :<br><span class=\"quote\">&gt;Blizzard Social Tab<\\/span><br><span class=\"quote\">&gt;NA -http:\\/\\/blizzard.com\\/invite\\/paGDfZa<wbr>X<\\/span><br><span class=\"quote\">&gt;EU -http:\\/\\/blizzard.com\\/invite\\/K0YLXSn<wbr>vk<\\/span><br><span class=\"quote\">&gt;In-game - Type &quot;\\/join \\/vg\\/&quot; in the chat<\\/span><br><br>Previous : <a href=\"\\/vg\\/thread\\/230919359#p230919359\" class=\"quotelink\">&gt;&gt;230919359<\\/a>",
			"author": "Anonymous",
			"author_trip": "Ep8pui8Vw2",
			"author_type": "Founder",
			"author_type_id": "founder",
			"country_code": "us",
			"country_name": "United States",
			"image_file": "YC9KyJE.jpg",
			"image_4chan": "1539575674701.jpg",
			"image_md5": "szdeY2WkImwGp\\/MR3LHICg==",
			"image_filesize": 159465,
			"image_dimensions": json.dumps({"w": 1200, "h": 1600, "tw": 187, "th": 250}),
			"semantic_url": "heroes-of-the-storm-general-hotsg",
			"unsorted_data": json.dumps({})}

		for field in expected:
			self.assertEqual(expected[field], post[field])

	def test_post_flags(self):
		"""
		Test correct mapping of 4chan API response data to database records
		"""
		(scraper, threaddata) = self.load_thread("4chan_json/thread_valid_onepost.json")
		postdata = threaddata["posts"][0]

		def change_and_check(scraper, postdata, postfield, field, value, before=None, after=None):
			"""
			Helper function to incrementally check assignment of separate values

			:param ThreadScraper scraper:
			:param dict postdata:
			:param str postfield:
			:param str field:
			:param value:
			:param before:
			:param after:
			:return:
			"""
			if before is None:
				before = postdata[postfield]
			if after is None:
				after = value

			self.tearDown()
			self.setUp()
			scraper.process({"posts": [postdata]}, job=self.job)
			post = self.db.fetchone("SELECT * FROM posts")
			self.assertNotEqual(post, None)
			self.assertEqual(post[field], before)

			postdata[postfield] = value
			self.tearDown()
			self.setUp()
			scraper.process({"posts": [postdata]}, job=self.job)
			post = self.db.fetchone("SELECT * FROM posts")
			self.assertNotEqual(post, None)
			self.assertEqual(post[field], after)

			return postdata

		# todo: image_file, image_4chan, image_dimensions
		# unsorted_data is tested in a separate test

		postdata = change_and_check(scraper, postdata, "sub", "subject", "changed test subject")
		postdata = change_and_check(scraper, postdata, "com", "body", "changed test body")
		postdata = change_and_check(scraper, postdata, "name", "author", "changed test name")
		postdata = change_and_check(scraper, postdata, "trip", "author_trip", "changedtesttrip")
		postdata = change_and_check(scraper, postdata, "id", "author_type", "Developer")
		postdata = change_and_check(scraper, postdata, "capcode", "author_type_id", "developer")
		postdata = change_and_check(scraper, postdata, "country", "country_code", "nl")
		postdata = change_and_check(scraper, postdata, "country_name", "country_name", "Netherlands")
		postdata = change_and_check(scraper, postdata, "semantic_url", "semantic_url", "changed_semantic_url")
		postdata = change_and_check(scraper, postdata, "md5", "image_md5", "szdeY2WkImwGp\\/MR3LHICg==")
		postdata = change_and_check(scraper, postdata, "fsize", "image_filesize", 12312345)

		postdata["ext"] = ".png"
		postdata = change_and_check(scraper, postdata, "filename", "image_file", "changedtestfile",
									before=postdata["filename"] + ".png", after="changedtestfile.png")
		postdata = change_and_check(scraper, postdata, "tim", "image_4chan", 1386720000000, before="1539575674701.png",
									after="1386720000000.png")

		del postdata["w"]
		del postdata["h"]
		del postdata["tn_w"]
		del postdata["tn_h"]
		jdict = json.dumps({})
		dimensions = json.dumps({"w": 150, "h": 150, "tw": 75, "th": 75})

		postdata = change_and_check(scraper, postdata, "w", "image_dimensions", 150, before=jdict, after=jdict)
		postdata = change_and_check(scraper, postdata, "h", "image_dimensions", 150, before=jdict, after=jdict)
		postdata = change_and_check(scraper, postdata, "tn_w", "image_dimensions", 75, before=jdict, after=jdict)
		postdata = change_and_check(scraper, postdata, "tn_h", "image_dimensions", 75, before=jdict, after=dimensions)

	def test_create_thread(self):
		"""
		Test whether thread gets added to database
		"""
		(scraper, threaddata) = self.load_thread("4chan_json/thread_valid.json")
		threaddata["posts"] = threaddata["posts"][:1]

		scraper.process(threaddata, job=self.job)
		threads = self.db.fetchone("SELECT COUNT(*) AS num FROM threads")["num"]
		self.assertEqual(threads, 1)

	def test_thread_data(self):
		"""
		Test whether basic thread data gets imported correctly
		"""
		(scraper, threaddata) = self.load_thread("4chan_json/thread_valid.json")
		scraper.process(threaddata, job=self.job)

		thread = self.db.fetchone("SELECT * FROM threads")
		expected = {
			"id": 231108796,
			"board": "test",
			"timestamp": 1539575674,
			"timestamp_modified": 1539575674,
			"post_last": 231109274,
			"num_unique_ips": 5,
			"num_replies": 6,
			"num_images": 6,
			"limit_bump": False,
			"limit_image": False,
			"is_sticky": False,
			"is_closed": False,
			"index_positions": None
		}

		for field in expected:
			self.assertEqual(thread[field], expected[field])

	def test_thread_flags(self):
		"""
		Test correct assignment of thread flags
		"""
		(scraper, threaddata) = self.load_thread("4chan_json/thread_valid.json")
		postdata = threaddata["posts"][0]

		def change_and_check(scraper, threaddata, field, test):
			"""
			Helper function to incrementally change values and check result

			:param ThreadScraper scraper:  Scraper to process with
			:param dict threaddata:  Thread data to process
			:param str field:  Thread field to test with
			:param test:  Value to test against
			:return:
			"""
			self.tearDown()
			self.setUp()
			scraper.process({"posts": [threaddata]}, job=self.job)
			thread = self.db.fetchone("SELECT * FROM threads")
			self.assertNotEqual(thread, None)
			self.assertEqual(thread[field], test)

		postdata["bumplimit"] = 1
		change_and_check(scraper, postdata, "limit_bump", True)

		postdata["imagelimit"] = 1
		change_and_check(scraper, postdata, "limit_image", True)

		postdata["sticky"] = 1
		change_and_check(scraper, postdata, "is_sticky", True)

		postdata["closed"] = 1
		change_and_check(scraper, postdata, "is_closed", True)

		postdata["archived_on"] = 1539575674
		change_and_check(scraper, postdata, "timestamp_archived", 0)

		postdata["archived"] = 1
		change_and_check(scraper, postdata, "timestamp_archived", 1539575674)

	def test_deleted_post(self):
		"""
		Test if deleted posts are properly detected if they are missing from a subsequent scrape
		"""
		(scraper, threaddata) = self.load_thread("4chan_json/thread_valid.json")
		scraper.process(threaddata, job=self.job)

		(scraper, threaddata) = self.load_thread("4chan_json/thread_valid_deletedpost.json")
		updated = scraper.process(threaddata, job=self.job)
		self.assertNotIsInstance(updated, bool)

		deleted = self.db.fetchone("SELECT COUNT(*) AS num FROM posts WHERE timestamp_deleted > 0")["num"]
		self.assertEqual(deleted, 1)

	def test_deleted_replace(self):
		"""
		Test if deleted posts are properly detected if they are missing from a subsequent scrape but the number of
		replies has remained the same
		:return:
		"""
		(scraper, threaddata) = self.load_thread("4chan_json/thread_valid.json")
		scraper.process(threaddata, job=self.job)

		(scraper, threaddata) = self.load_thread("4chan_json/thread_valid_replacedpost.json")
		updated = scraper.process(threaddata, job=self.job)
		self.assertNotIsInstance(updated, bool)

		deleted = self.db.fetchone("SELECT COUNT(*) AS num FROM posts WHERE timestamp_deleted > 0")["num"]
		self.assertEqual(deleted, 1)

	@unittest.skipIf(not os.path.isdir(get_absolute_folder(config.PATH_IMAGES)), "no valid image folder configured")
	def test_image_queued(self):
		"""
		Test if images are queued when scraped
		"""
		(scraper, threaddata) = self.load_thread("4chan_json/thread_valid.json")
		scraper.process(threaddata, job=self.job)

		jobs = self.db.fetchone("SELECT COUNT(*) AS num FROM jobs WHERE jobtype = %s", ("image",))["num"]
		self.assertEqual(jobs, 6)

	@unittest.skipIf(not os.path.isdir(get_absolute_folder(config.PATH_IMAGES)), "no valid image folder configured")
	def test_image_queue_data(self):
		"""
		Test if image data is properly saved in job details when queuing for download
		"""
		(scraper, threaddata) = self.load_thread("4chan_json/thread_valid_onepost.json")
		scraper.process(threaddata, job=self.job)

		job = self.db.fetchone("SELECT * FROM jobs WHERE jobtype = %s", ("image",))
		self.assertNotEqual(job, None)

		path = get_absolute_folder(config.PATH_IMAGES) + "/" + "3af66a356ef3faf5e847e1523b59786c.jpg"
		expected = {
			"jobtype": "image",
			"remote_id": "szdeY2WkImwGp\/MR3LHICg==",
			"details": {
				"board": self.job["details"]["board"],
				"ext": ".jpg",
				"tim": 1539575674701,
				"destination": path
			},
			"timestamp": scraper.loop_time,
			"claim_after": 0,
			"claimed": 0,
			"attempts": 0
		}

		job["details"] = json.loads(job["details"])
		for field in expected:
			self.assertEqual(expected[field], job[field])


if __name__ == '__main__':
	unittest.main()
