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
		try:
			query = DataSet(key=self.job.data["remote_id"], db=self.db)
		except ValueError:
			self.job.finish()
			return

		if not query.is_finished():
			self.job.release(delay=5)
			return

		# queue top non-standard words
		file_prefix = "/%i-%s-%s" % (query.data["timestamp"], query.parameters["platform"], query.parameters["board"])
		analysis = DataSet(parameters={
			"next": {
				"type": "vectorise-tokens",
				"parameters": {
					"next": {
						"type": "vector-ranker",
						"parameters": {
							"amount": True,
							"top": 15,
							"copy_to": config.PATH_SNAPSHOTDATA + "%s-top-neologisms.csv" % file_prefix
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

		self.job.finish()
