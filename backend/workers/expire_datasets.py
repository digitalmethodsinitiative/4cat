"""
Delete old datasets
"""
import time

from backend.abstract.worker import BasicWorker
from common.lib.dataset import DataSet
from common.config_manager import config

class ThingExpirer(BasicWorker):
	"""
	Delete old items

	Deletes expired datasets. This may be useful for two reasons: to conserve
	disk space and if the user agreement of a particular data source does not
	allow storing scraped or extracted data for longer than a given amount of
	time, as is the case for e.g. Tumblr.

	Also deletes expired notifications.
	"""
	type = "expire-datasets"
	max_workers = 1

	ensure_job = {"remote_id": "localhost", "interval": 300}

	def work(self):
		"""
		Go through all datasources, and if it is configured to automatically
		delete old datasets, do so for all qualifying datasets.

		Next, delete all expired notifications.
		:return:
		"""
		datasets = []
		expiration = config.get("expire.datasources", {})

		# first get datasets for which the data source specifies that they need
		# to be deleted after a certain amount of time
		for datasource_id in self.all_modules.datasources:
			datasource = self.all_modules.datasources[datasource_id]

			# default = never expire
			if not expiration.get(datasource_id):
				continue

			cutoff = time.time() - int(expiration[datasource_id].get("timeout"))
			datasets += self.db.fetchall(
				"SELECT key FROM datasets WHERE key_parent = '' AND parameters::json->>'datasource' = %s AND timestamp < %s",
				(datasource_id, cutoff))

		# and now find datasets that have their expiration date set
		# individually
		cutoff = int(time.time())
		datasets += self.db.fetchall("SELECT key FROM datasets WHERE parameters::json->>'expires-after' IS NOT NULL AND (parameters::json->>'expires-after')::int < %s", (cutoff,))

		# we instantiate the dataset, because its delete() method does all
		# the work (e.g. deleting child datasets) for us
		for dataset in datasets:
			dataset = DataSet(key=dataset["key"], db=self.db)
			dataset.delete()
			self.log.info("Deleting dataset %s/%s (expired per configuration)" % (dataset.parameters.get("datasource", "unknown"), dataset.key))

		# and now, notifications
		self.db.execute("DELETE FROM users_notifications WHERE timestamp_expires IS NOT NULL AND timestamp_expires < %s" % (int(time.time()),))

		self.job.finish()
