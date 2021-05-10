"""
Delete old datasets
"""
import time

from backend.abstract.worker import BasicWorker
from common.lib.dataset import DataSet

class DatasetExpirer(BasicWorker):
	"""
	Delete old datasets

	This may be useful for two reasons: to conserve disk space and if the user
	agreement of a particular data source does not allow storing scraped or
	extracted data for longer than a given amount of time, as is the case for
	e.g. Tumblr.
	"""
	type = "expire-datasets"
	max_workers = 1

	def work(self):
		"""
		Go through all datasources, and if it is configured to automatically
		delete old datasets, do so for all qualifying datasets
		:return:
		"""
		for datasource_id in self.all_modules.datasources:
			datasource = self.all_modules.datasources[datasource_id]

			# default = never expire
			if not datasource.get("expire-datasets", None):
				continue

			cutoff = time.time() - datasource.get("expire-datasets")
			datasets = self.db.fetchall(
				"SELECT key FROM datasets WHERE key_parent = '' AND parameters::json->>'datasource' = %s AND timestamp < %s",
				(datasource_id, cutoff))

			# we instantiate the dataset, because its delete() method does all
			# the work (e.g. deleting child datasets) for us
			for dataset in datasets:
				dataset = DataSet(key=dataset["key"], db=self.db)
				dataset.delete()
				self.log.info("Deleting dataset %s/%s (expired per configuration)" % (datasource, dataset.key))

		self.job.finish()
