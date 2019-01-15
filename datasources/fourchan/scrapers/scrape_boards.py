"""
4Chan board scraper - indexes threads and queues them for scraping
"""

from backend.abstract.scraper import BasicJSONScraper
from backend.lib.exceptions import JobAlreadyExistsException


class BoardScraper4chan(BasicJSONScraper):
	"""
	Scrape 4chan boards

	The threads found aren't saved themselves, but new jobs are created to scrape the
	individual threads so post data can be saved
	"""
	type = "4chan-board"
	max_workers = 2  # should probably be equivalent to the amount of boards to scrape

	required_fields = ["no", "last_modified"]
	position = 0

	def process(self, data):
		"""
		Process scraped board data

		For each thread, a record is inserted into the database if it does not exist yet

		:param dict data: The board data, parsed JSON data
		"""
		new_threads = 0
		if not data:
			self.log.error("No thread data from board scrape of /%s/" % self.job.data["remote_id"])
			return False

		for page in data:
			for thread in page["threads"]:
				self.position += 1
				new_threads += self.save_thread(thread)

		self.log.info("Board scrape for %s/ yielded %i new threads" % (self.job.data["remote_id"], new_threads))

	def save_thread(self, thread):
		"""
		Save thread

		:param dict thread:  Thread data
		:return int:  Number of new threads created (so 0 or 1)
		"""

		# check if we have everything we need
		missing = set(self.required_fields) - set(thread.keys())
		if missing != set():
			self.log.warning("Missing fields %s in scraped thread, ignoring" % repr(missing))
			return False

		board_id = self.job.data["remote_id"].split("/").pop()
		thread_id = thread["id"] if "id" in thread else thread["no"]

		thread_data = {
			"id": thread_id,
			"board": board_id,
			"index_positions": ""
		}

		# schedule a job for scraping the thread's posts
		try:
			jobtype = self.prefix + "-thread"
			self.queue.add_job(jobtype=jobtype, remote_id=thread["no"], details={"board": board_id})
		except JobAlreadyExistsException:
			# this might happen if the workers can't keep up with the queue
			pass

		# add database record for thread, if none exists yet
		# 8chan supports cyclical threads which have an ID that is *not* the first post's. The
		# following line accounts for this.
		thread_row = self.db.fetchone("SELECT * FROM threads_" + self.prefix + " WHERE id = %s", (str(thread_id),))
		new_thread = 0
		if not thread_row:
			new_thread += 1
			self.db.insert("threads_" + self.prefix, thread_data)

		# update timestamps and position
		position_update = str(self.loop_time) + ":" + str(self.position) + ","
		self.db.execute("UPDATE threads_" + self.prefix + " SET timestamp_scraped = %s, timestamp_modified = %s,"
						"index_positions = CONCAT(index_positions, %s) WHERE id = %s",
						(self.loop_time, thread["last_modified"], position_update, str(thread_id)))

		return new_thread

	def get_url(self):
		"""
		Get URL to scrape for the current job

		:return string: URL to scrape
		"""
		board_id = self.job.data["remote_id"].split("/").pop()
		return "http://a.4cdn.org/%s/threads.json" % board_id
