"""
A job queue, to divide work over the workers
"""
import time
import json

from backend.lib.job import Job
import psycopg2


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

	def get_job(self, jobtype, timestamp=-1):
		"""
		Get job of a specific type

		Returns a job's data. The `details` column is parsed JSON, and can thus contain all
		kinds of data.

		:param string jobtype:  Job type
		:param int timestamp:  Find jobs that may be claimed after this timestamp. If set to
							   a negative value (default), any job with a "claim after" time
							   earlier than the current time is selected.
		:return dict: Job data, or `None` if no job was found
		"""
		if timestamp < 0:
			timestamp = int(time.time())

		job = self.db.fetchone((
			"SELECT * FROM jobs"
			"        WHERE jobtype = %s"
			"          AND timestamp_claimed = 0"
			"          AND timestamp_after < %s"
			"          AND (interval = 0 OR timestamp_lastclaimed + interval < %s)"
			"    ORDER BY timestamp ASC"
			"       LIMIT 1;"),
			(jobtype, timestamp, timestamp))

		return Job.get_by_data(job, database=self.db) if job else None

	def get_all_jobs(self, jobtype="*", remote_id=False):
		"""
		Get all unclaimed (and claimable) jobs

		:param string jobtype:  Type of job, "*" for all types
		:param string remote_id:  Remote ID, takes precedence over `jobtype`
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

		now = int(time.time())
		replacements.append(now)
		replacements.append(now)

		query = "SELECT * FROM jobs %s" % filter
		query += ("        AND timestamp_claimed = 0"
				  "              AND timestamp_after < %s"
				  "              AND (interval = 0 OR timestamp_lastclaimed + interval < %s)"
				  "         ORDER BY timestamp ASC")

		try:
			jobs = self.db.fetchall(query, replacements)
		except psycopg2.ProgrammingError:
			# there seems to be a bug with psycopg2 where it sometimes raises
			# this for empty query results even though it shouldn't. this
			# doesn't seem to indicate an actual problem so we catch the
			# exception and return an empty list
			# https://github.com/psycopg/psycopg2/issues/346
			jobs = []

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

	def add_job(self, jobtype, details=None, remote_id=0, claim_after=0, interval=0):
		"""
		Add a new job to the queue

		There can only be one job for any combination of job type and remote id. If a job
		already exists for the given combination, no new job is added.

		:param jobtype:  Job type
		:param details:  Job details - may be empty, will be stored as JSON
		:param remote_id:  Remote ID of object to work on. For example, a post or thread ID
		:param claim_after:  Absolute timestamp after which job may be claimed
		:param interval:  If this is not zero, the job is made a repeating job,
		                  which will be repeated at most every `interval` seconds.

		:return Job: A job that matches the input type and remote ID. This may
		             be a newly added job or an existing that matched the same
		             combination (which is required to be unique, so no new job
		             with those parameters could be queued, and the old one is
		             just as valid).
		"""
		data =  data={
			"jobtype": jobtype,
			"details": json.dumps(details),
			"timestamp": int(time.time()),
			"timestamp_claimed": 0,
			"timestamp_lastclaimed": 0,
			"remote_id": remote_id,
			"timestamp_after": claim_after,
			"interval": interval,
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
