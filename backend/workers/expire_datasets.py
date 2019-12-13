"""
Delete old datasets
"""
import time

from backend.abstract.worker import BasicWorker
from backend.lib.dataset import DataSet

class DatasetExpirer(BasicWorker):
	"""
	Delete old datasets
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
				"SELECT key FROM queries WHERE key_parent = '' AND parameters::json->>'datasource' = %s AND timestamp < %s",
				(datasource_id, cutoff))

			# we instantiate the dataset, because its delete() method does all
			# the work (e.g. deleting child datasets) for us
			for dataset in datasets:
				dataset = DataSet(key=dataset["key"], db=self.db)
				dataset.delete()
				self.log.info("Deleting dataset %s/%s (expired per configuration)" % (datasource, dataset.key))

		self.job.finish()
