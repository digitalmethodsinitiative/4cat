import math
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
			# a valid path to a place to store the snapshot data is needed
			self.job.finish(delete=True)
			return

		for platform in config.PLATFORMS:
			if not config.PLATFORMS[platform].get("snapshots", False)\
					or not config.PLATFORMS[platform].get("boards", False) \
					or config.PLATFORMS[platform]["boards"] == ["*"]:
				# we need specific boards to queue the snapshot for
				continue

			for board in config.PLATFORMS[platform]["boards"]:
				type = "%s-search" % platform

				# usually we just want the past 24 hours, but this can be
				# changed through job parameters if needed, for example
				# if data for a specific day needs to be recalculated
				if not self.job.details or "epoch" not in self.job.details:
					# make epoch closest timestamp that is the original
					# timestamp plus a multiple of the interval while still
					# being less than or equal to the claim time

					# this ensures the snapshots will always have exactly a
					# 24-hour gap between them
					repeats = math.floor(
						(self.job.data["timestamp_lastclaimed"] - self.job.data["timestamp"]) / self.job.data[
							"interval"])
					epoch = self.job.data["timestamp"] + (repeats * self.job.data["interval"])
				else:
					epoch = self.job.details["epoch"]

				# create a new search query that simply returns all posts
				# between the given timestamps
				query = DataSet(parameters={
					"platform": platform,
					"board": board,
					"body_query": "",
					"subject_query": "",
					"min_date": epoch - 86400,
					"max_date": epoch,
					"country_flag": "all",
					"full_thread": False,
					"dense_threads": False,
					"user": "daily-snapshot",
					"dense_percentage": 0,
					"dense_country_percentage": 0,
					"random_amount": False,
					"dense_length": 0
				}, type=type, db=self.db)

				# run the search and queue further analysis for once the
				# search is done
				self.queue.add_job(type, remote_id=query.key)
				self.queue.add_job("analyse-snapshot", remote_id=query.key)

		self.job.finish()
