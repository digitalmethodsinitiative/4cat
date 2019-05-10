import time

import config

from backend.abstract.worker import BasicWorker
from backend.lib.query import DataSet


class SnapshotAnalyser(BasicWorker):
	"""
	Run analyses on the daily snapshot
	"""
	type = "analyse-snapshot"
	max_workers = 1

	def work(self):
		# make sure the search query exists, because it is the starting point
		# for all further analysis
		try:
			query = DataSet(key=self.job.data["remote_id"], db=self.db)
		except ValueError:
			self.job.finish()
			return

		# if the search is not finished yet, check again in 5 seconds
		if not query.is_finished():
			self.job.release(delay=5)
			return

		# queue top non-standard words
		file_prefix = "/%i-%s-%s" % (query.parameters["max_date"], query.parameters["platform"], query.parameters["board"])
		analysis = DataSet(parameters={
			"next": {
				"type": "vectorise-tokens",
				"parameters": {
					"next": {
						"type": "vector-ranker",
						"parameters": {
							"amount": True,
							"top": 15,
							"copy_to": config.PATH_SNAPSHOTDATA + "%s-neologisms.csv" % file_prefix
						}
					}
				}
			},
			"echobrackets": False,
			"stem": False,
			"lemmatise": False,
			"timeframe": "all",
			"stopwords": "terrier",
			"filter": "infochimps"
		}, type="tokenise-posts", db=self.db, parent=query.key)
		self.queue.add_job("tokenise-posts", remote_id=analysis.key)

		# queue top countries
		analysis = DataSet(parameters={
			"top": 15,
			"copy_to": config.PATH_SNAPSHOTDATA + "%s-countries.csv" % file_prefix
		}, type="count-countries", db=self.db, parent=query.key)
		self.queue.add_job("count-countries", remote_id=analysis.key)

		# queueing is done, job finished
		self.job.finish()
