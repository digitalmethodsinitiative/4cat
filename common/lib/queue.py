"""
A job queue, to divide work over the workers
"""
import time
import json

from common.lib.job import Job


class JobQueue:
	"""
	A simple job queue

	Jobs are basically database records. The job has some information that a worker
	can use to do its job. The job queue is shared between workers so that nothing
	is done twice.
	"""
	db = None
	log = None

	def __init__(self, logger, database):
		"""
		Set up database handler
		"""
		self.log = logger

		self.db = database

	def get_job(self, jobtype, timestamp=-1, restrict_claimable=True):
		"""
		Get job of a specific type

		Returns a job's data. The `details` column is parsed JSON, and can thus contain all
		kinds of data.

		:param string jobtype:  Job type
		:param int timestamp:  Find jobs that may be claimed after this timestamp. If set to
							   a negative value (default), any job with a "claim after" time
							   earlier than the current time is selected.
		:param bool restrict_claimable:  Only return jobs that may be claimed
		according to their parameters
		:return dict: Job data, or `None` if no job was found
		"""
		if timestamp < 0:
			timestamp = int(time.time())

		# select the number of jobs of the same type that have been queued for
		# longer than the job as well
		replacements = [jobtype]
		query = (
			"SELECT main_queue.* FROM jobs AS main_queue"
			"        WHERE main_queue.jobtype = %s"
		)

		if restrict_claimable:
			# claimability is determined through various timestamps
			query += (
			"          AND main_queue.timestamp_claimed = 0"
			"          AND main_queue.timestamp_after < %s"
			"          AND (main_queue.interval = 0 OR main_queue.timestamp_lastclaimed + main_queue.interval < %s)"
			)
			replacements.append(timestamp)
			replacements.append(timestamp)

		query += "    ORDER BY main_queue.timestamp ASC LIMIT 1;"

		job = self.db.fetchone(query, tuple(replacements))

		return Job.get_by_data(job, database=self.db) if job else None

	def get_all_jobs(self, jobtype="*", queue_id="*", limit=None, offset=None, remote_id=False, restrict_claimable=True):
		"""
		Get all unclaimed (and claimable) jobs

		:param str jobtype:  Type of job, "*" for all types
		:param str queue_id:  ID of queue, "*" for all queues
		:param str remote_id:  Remote ID, takes precedence over `jobtype` and
		  `queue_id`
		:param bool restrict_claimable:  Only return jobs that may be claimed
		  according to their parameters
		:return list:
		"""
		replacements = []
		if remote_id:
			filter = "WHERE remote_id = %s"
			replacements = [remote_id]
		elif jobtype != "*":
			filter = "WHERE jobtype = %s"
			replacements = [jobtype]
		else:
			filter = "WHERE jobtype != ''"

		if queue_id != "*" and not remote_id:
			filter += " AND queue_id = %s"
			replacements.append(queue_id)

		query = "SELECT * FROM jobs %s" % filter

		if restrict_claimable:
			query += ("        AND timestamp_claimed = 0"
					  "              AND timestamp_after < %s"
					  "              AND (interval = 0 OR timestamp_lastclaimed + interval < %s)")

			now = int(time.time())
			replacements.append(now)
			replacements.append(now)

		query += "         ORDER BY timestamp ASC"

		if limit is not None:
			query += " LIMIT %s"
			replacements.append(limit)
		if offset is not None:
			query += " OFFSET %s"
			replacements.append(offset)

		jobs = self.db.fetchall(query, replacements)

		return [Job.get_by_data(job, self.db) for job in jobs if job]

	def get_job_count(self, jobtype="*"):
		"""
		Get total number of jobs

		:param jobtype:  Type of jobs to count. Default (`*`) counts all jobs.
		:return int:  Number of jobs
		"""
		if jobtype == "*":
			count = self.db.fetchone("SELECT COUNT(*) FROM jobs;", ())
		else:
			count = self.db.fetchone("SELECT COUNT(*) FROM jobs WHERE jobtype = %s;", (jobtype,))

		return int(count["count"])

	def add_job(self, job_or_type, details=None, remote_id=None, dataset=None, claim_after=0, interval=0, queue_id=None):
		"""
		Add a new job to the queue

		There can only be one job for any combination of job type and remote id. If a job
		already exists for the given combination, no new job is added.

		:param job_or_type:  Job type, or a Worker object; in the latter case the
		  worker type ID is used
		:param details:  Job details - may be empty, will be stored as JSON
		:param remote_id:  ID of object to work on. For example, a post or
		  thread ID, or a dataset key. If a DataSet object is passed, the
		  DataSet key is used
		:param dataset:  DataSet object to work on. If passed, `remote_id` is
		  set to the dataset's `key` attribute.
		:param claim_after:  Absolute timestamp after which job may be claimed
		:param queue_id:  ID of the queue the job is in. When `None`, set to
		  job type ID. If empty, and a `BasicWorker` is passed as `jobtype`
		  and `DataSet` object is passed as remote_id, use the result of
		  `jobtype.get_queue_id(remote_id.parameters)`
		:param interval:  If this is not zero, the job is made a repeating job,
		  which will be repeated at most every `interval` seconds.

		:return Job: A job that matches the input type and remote ID. This may
		  be a newly added job or an existing that matched the same combination
		  (which is required to be unique, so no new job with those parameters
		  could be queued, and the old one is just as valid).
		"""
		if remote_id is None and dataset is None:
			raise ValueError("You must specify either remote_id or dataset for add_job().")

		# we cannot import BasicWorker or DataSet here for a direct class check
		# due to circular imports, so use this heuristic instead
		have_worker = type(job_or_type) is not str and hasattr(job_or_type, "type")

		if dataset:
			remote_id = dataset.key

		if have_worker:
			queue_id = job_or_type.get_queue_id(remote_id=remote_id, details=details, dataset=dataset)
			job_or_type = job_or_type.type
		else:
			queue_id = job_or_type
			
		data = {
			"jobtype": job_or_type,
			"details": json.dumps(details),
			"timestamp": int(time.time()),
			"timestamp_claimed": 0,
			"timestamp_lastclaimed": 0,
			"remote_id": remote_id,
			"timestamp_after": claim_after,
			"interval": interval,
			"queue_id": queue_id,
			"attempts": 0
		}

		self.db.insert("jobs", data, safe=True, constraints=("jobtype", "remote_id"))

		return Job.get_by_data(data, database=self.db)

	def release_all(self):
		"""
		Release all jobs

		All claimed jobs are released. This is useful to run when the backend is restarted.
		"""
		self.db.execute("UPDATE jobs SET timestamp_claimed = 0")