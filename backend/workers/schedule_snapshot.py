import os

import config

from backend.abstract.worker import BasicWorker
from backend.lib.query import DataSet


class SnapshotScheduler(BasicWorker):
	"""
	Schedule a daily snapshot query and subsequent statistics generation
	"""
	type = "schedule-snapshot"
	max_workers = 1

	def work(self):
		if not config.PATH_SNAPSHOTDATA or not os.path.exists(config.PATH_SNAPSHOTDATA):
			self.job.finish(delete=True)
			return

		for platform in config.PLATFORMS:
			if "boards" not in config.PLATFORMS[platform] or "interval" not in config.PLATFORMS[platform]:
				continue

			for board in config.PLATFORMS[platform]["boards"]:
				type = "%s-search" % platform

				query = DataSet(parameters={
					"platform": platform,
					"board": board,
					"body_query": "",
					"subject_query": "",
					"min_date": self.loop_time - 86400,
					"max_date": self.loop_time,
					"country_flag": "all",
					"full_thread": False,
					"user": "anonymous"
				}, type=type, db=self.db)

				self.queue.add_job(type, remote_id=query.key)
				self.queue.add_job("analyse-snapshot", remote_id=query.key)

		self.job.finish()