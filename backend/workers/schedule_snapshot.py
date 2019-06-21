import math

from pathlib import Path

import config

from backend.abstract.worker import BasicWorker
from backend.lib.dataset import DataSet


class SnapshotScheduler(BasicWorker):
	"""
	Schedule a daily snapshot query and subsequent statistics generation
	"""
	type = "schedule-snapshot"
	max_workers = 1

	def work(self):
		if not config.PATH_SNAPSHOTDATA or not Path(config.PATH_SNAPSHOTDATA).exists():
			# a valid path to a place to store the snapshot data is needed
			self.job.finish(delete=True)
			return

		for datasource in config.DATASOURCES:
			if not config.DATASOURCES[datasource].get("snapshots", False)\
					or not config.DATASOURCES[datasource].get("boards_snapshot", False):
				# we need specific boards to queue the snapshot for
				continue

			for board in config.DATASOURCES[datasource]["boards_snapshot"]:
				type = "%s-search" % datasource

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
					"datasource": datasource,
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
				}, type="search", db=self.db)

				# run the search and queue further analysis for once the
				# search is done
				self.queue.add_job(type, remote_id=query.key)
				self.queue.add_job("analyse-snapshot", remote_id=query.key)

		self.job.finish()
