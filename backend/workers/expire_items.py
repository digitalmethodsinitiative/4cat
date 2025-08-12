"""
Delete old items
"""
import datetime
import time
import re

from backend.lib.worker import BasicWorker
from common.lib.dataset import DataSet
from common.lib.exceptions import DataSetNotFoundException, WorkerInterruptedException

from common.lib.user import User
from common.config_manager import ConfigWrapper


class ThingExpirer(BasicWorker):
	"""
	Delete old items

	Deletes expired datasets. This may be useful for two reasons: to conserve
	disk space and if the user agreement of a particular data source does not
	allow storing scraped or extracted data for longer than a given amount of
	time, as is the case for e.g. Tumblr.

	Also deletes users that have an expiration date that is not zero. Users
	with a close expiration date get a notification.

	Also deletes expired notifications.
	"""
	type = "expire-datasets"
	max_workers = 1

	@classmethod
	def ensure_job(cls, config=None):
		"""
		Ensure that the expirer is always running

		This is used to ensure that the expirer is always running, and if it is
		not, it will be started by the WorkerManager.

		:return:  Job parameters for the worker
		"""
		return {"remote_id": "localhost", "interval": 300}

	def work(self):
		"""
		Delete datasets, users and notifications
		"""

		self.expire_datasets()
		self.expire_users()
		self.expire_notifications()

		self.job.finish()

	def expire_datasets(self):
		"""
		Delete expired datasets
		"""
		# find candidates
		# todo: make this better - this can be a lot of datasets!
		datasets = self.db.fetchall("""
			SELECT key FROM datasets
			 WHERE parameters::json->>'keep' IS NULL
		""")

		for dataset in datasets:
			if self.interrupted:
				raise WorkerInterruptedException("Interrupted while expiring datasets")

			# the dataset creator's configuration context determines expiration
			try:
				dataset = DataSet(key=dataset["key"], db=self.db)
				wrapper = ConfigWrapper(self.config, user=User.get_by_name(self.db, dataset.creator))
				if dataset.is_expired(config=wrapper):
					self.log.info(f"Deleting dataset {dataset.key} (expired)")
					dataset.delete()

			except DataSetNotFoundException:
				# dataset already deleted I guess?
				pass

	def expire_users(self):
		"""
		Delete expired users

		Users can have a `delete-after` parameter in their user data which
		indicates a date or time after which the account should be deleted.

		The date can be in YYYY-MM-DD format or a unix (UTC) timestamp. If
		the current date is after the given date the account is deleted. If the
		expiration date is within 7 days a notification is added for the user
		to warn them.
		"""
		expiring_users = self.db.fetchall("SELECT * FROM users WHERE userdata::json->>'delete-after' IS NOT NULL;")
		now = datetime.datetime.now()

		for expiring_user in expiring_users:
			if self.interrupted:
				raise WorkerInterruptedException("Interrupted while expiring users")

			user = User.get_by_name(self.db, expiring_user["name"], config=self.config)
			username = user.data["name"]

			# parse expiration date if available
			delete_after = user.get_value("delete-after")
			if not delete_after:
				continue

			if re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", str(delete_after)):
				expires_at = datetime.datetime.strptime(delete_after, "%Y-%m-%d")
			elif re.match(r"^[0-9]+$", str(delete_after)):
				expires_at = datetime.datetime.fromtimestamp(int(delete_after))
			else:
				self.log.warning(f"User {username} has invalid expiration date {delete_after}")
				continue

			# check if expired...
			if expires_at < now:
				self.log.info(f"User {username} expired - deleting user and datasets")
				user.delete()
			else:
				warning_notification = f"WARNING: This account will be deleted at <time datetime=\"{expires_at.strftime('%C')}\">{expires_at.strftime('%-d %B %Y %H:%M')}</time>. Make sure to back up your data before then."
				user.add_notification(warning_notification)

	def expire_notifications(self):
		"""
		Delete expired notifications

		Pretty simple!
		"""
		self.db.execute(f"DELETE FROM users_notifications WHERE timestamp_expires IS NOT NULL AND timestamp_expires < {time.time()}")
