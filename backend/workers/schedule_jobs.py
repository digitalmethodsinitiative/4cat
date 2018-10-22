"""
Schedules jobs so the other workers have something to do
"""
import config

from backend.lib.worker import BasicWorker


class JobScheduler(BasicWorker):
	"""
	This does no work itself, but schedules jobs for other workers at regular intervals.
	"""
	type = "scheduler"
	pause = 10
	max_workers = 1

	def work(self):
		"""
		Schedule a board scraping job at the first second of every minute
		:return:
		"""
		normalized_time = self.loop_time - (self.loop_time % 60) + 60

		jobs = self.queue.get_all_jobs()
		for board in config.SCRAPE_BOARDS:
			scheduled = False
			for job in jobs:
				if job["jobtype"] == "board" and job["remote_id"] == board:
					scheduled = True

			if not scheduled:
				self.log.info("Scheduling board scrape for /%s/" % board)
				self.queue.add_job("board", remote_id=board, claim_after=normalized_time)
