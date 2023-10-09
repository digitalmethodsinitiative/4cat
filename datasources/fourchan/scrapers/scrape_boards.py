"""
4Chan board scraper - indexes threads and queues them for scraping
"""

import json

from backend.lib.scraper import BasicJSONScraper
from common.lib.exceptions import JobAlreadyExistsException


class BoardScraper4chan(BasicJSONScraper):
	"""
	Scrape 4chan boards

	The threads found aren't saved themselves, but new jobs are created to scrape the
	individual threads so post data can be saved
	"""
	type = "fourchan-board"
	max_workers = 2  # should probably be equivalent to the amount of boards to scrape

	required_fields = ["no", "last_modified"]
	position = 0

	def process(self, data):
		"""
		Process scraped board data

		For each thread, a record is inserted into the database if it does not exist yet

		:param dict data: The board data, parsed JSON data
		"""
		self.datasource = self.type.split("-")[0]
		new_threads = 0

		if not data:
			self.log.error("No thread data from board scrape of %s/%s/" % (self.datasource, self.job.data["remote_id"]))
			return False

		index_thread_ids = []

		for page in data:
			if page.get('threads') is None:
				self.log.error(
					"No thread data from board scrape of %s/%s/" % (self.datasource, self.job.data["remote_id"]))
				return False

			for thread in page["threads"]:
				self.position += 1
				new_threads += self.save_thread(thread)
				index_thread_ids.append(thread["id"] if "id" in thread else thread["no"])

		self.log.info("Board scrape for %s/%s/ yielded %i new threads" % (self.datasource, self.job.data["remote_id"], new_threads))

		# Also update threads that were not yet seen as not archived or closed, but were also not in the index.
		# These were either archived or deleted by moderators.
		self.update_unindexed_threads(index_thread_ids)

	def save_thread(self, thread):
		"""
		Save thread

		:param dict thread:  Thread data
		:return int:  Number of new threads created (so 0 or 1)
		"""

		# 8kun for some reason doesn't always include last_modified
		# in that case the timestamp will be 0
		if self.datasource == "8kun" and "last_modified" in self.required_fields:
			self.required_fields.remove("last_modified")

		# check if we have everything we need
		missing = set(self.required_fields) - set(thread.keys())
		if missing != set():
			self.log.warning("Missing fields %s in scraped thread from %s/%s/, ignoring: got %s" % (repr(missing), self.datasource, self.job.data["remote_id"], repr(thread)))
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
			jobtype = self.type.replace("-board", "-thread")
			self.queue.add_job(jobtype=jobtype, remote_id=thread["no"], details={"board": board_id})
		except JobAlreadyExistsException:
			# this might happen if the workers can't keep up with the queue
			pass

		# add database record for thread, if none exists yet
		# 8chan supports cyclical threads which have an ID that is *not* the first post's. The
		# following line accounts for this.
		thread_row = self.db.fetchone("SELECT * FROM threads_" + self.prefix + " WHERE id = %s AND board = %s", (str(thread_id), board_id))
		new_thread = 0
		if not thread_row:
			new_thread += 1
			self.db.insert("threads_" + self.prefix, thread_data)

		replacements = [self.init_time, thread.get("last_modified", 0)]
		if "fourchan" in self.type:
			# update timestamps and position, but only for 4chan
			# other chans have different strategies and often have "infinite"
			# threads which would rapidly bloat the database with an infinite
			# stream of thread positions
			position_update = str(self.init_time) + ":" + str(self.position) + ","
			positions_bit = ", index_positions = CONCAT(index_positions, %s)"
			replacements.append(position_update)
		else:
			positions_bit = ""

		replacements.extend([str(thread_id), board_id])
		self.db.execute("UPDATE threads_" + self.prefix + " SET timestamp_scraped = %s, timestamp_modified = %s" + positions_bit + " WHERE id = %s AND board = %s",
						replacements)

		return new_thread

	def update_unindexed_threads(self, index_thread_ids):
		"""
		Add a job for threads that aren't in the index, but are also still marked as active
		(i.e. `timestamp_deleted` or `timestamp_archived` is still 0).

		:param index_thread_ids, list: List of dicts with threads that were in the index already.

		"""

		board_id = self.job.data["remote_id"].split("/").pop()
		
		# We're updating checking threads that
		# 1) are not in the index
		# 2) are not more than an hour old; we already covered older ones in the regular scrape,
		#	 and if not, it's likely that 4CAT wasn't running at the time, so we can't verify
		#	 whether the thread is archived or deleted.
		# 3) have 0 as a value for both `timestamp_deleted` and `timestamp_archived`
		unindexed_threads = self.db.fetchall("SELECT id FROM threads_" + self.prefix + " WHERE board = %s AND timestamp_deleted = 0 AND timestamp_archived = 0 AND timestamp_modified > (EXTRACT(epoch FROM NOW()) - 3600) AND id NOT IN %s",
			(board_id, tuple(index_thread_ids)))
		
		if unindexed_threads:

			to_check = 0
			
			for thread in unindexed_threads:
				# Schedule a job for scraping the thread's posts,
				# which also updates its deleted/archived status 
				try:
					# Add a new thread job if it isn't in the jobs table anymore
					jobtype = self.type.replace("-board", "-thread")
					query = "SELECT remote_id FROM jobs WHERE remote_id = '%s' AND details = '%s';" % (str(thread["id"]), json.dumps({"board": board_id}))
					remote_id = self.db.fetchone(query)
					
					if not remote_id:
						self.queue.add_job(jobtype=jobtype, remote_id=str(thread["id"]), details={"board": board_id})
						to_check += 1

				except JobAlreadyExistsException:
					# this might happen if the workers can't keep up with the queue
					pass

			if to_check:
				self.log.info("Board scrape for %s/%s/ yielded %s threads that disappeared from the index, updating their status" % (self.datasource, self.job.data["remote_id"], to_check))

	def get_url(self):
		"""
		Get URL to scrape for the current job

		:return string: URL to scrape
		"""
		board_id = self.job.data["remote_id"].split("/").pop()
		return "http://a.4cdn.org/%s/threads.json" % board_id