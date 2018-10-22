import unittest
import json
import time

from basic_testcase import FourcatTestCase
from backend.lib.queue import JobQueue, JobClaimedException


class TestJobQueue(FourcatTestCase):
	details = {"key1": "value1", "key2": "value2"}
	jobid = 1234
	basic_job = {
		"jobtype": "test",
		"details": json.dumps(details),
		"remote_id": jobid
	}
	basic_expected = {
		"jobtype": "test",
		"details": json.dumps(details),
		"remote_id": str(jobid),
		"claim_after": 0,
		"claimed": 0,
		"attempts": 0
	}

	def test_add_job(self):
		"""
		Test if a job can be successfully added to the queue
		"""

		queue = JobQueue(logger=self.log, database=self.db)
		queue.add_job("test", details=self.details, remote_id=self.jobid)

		job = self.db.fetchone("SELECT * FROM jobs")
		expected = {
			"jobtype": "test",
			"details": json.dumps(self.details),
			"remote_id": str(self.jobid),
			"claim_after": 0,
			"claimed": 0,
			"attempts": 0
		}

		for field in expected:
			with self.subTest(field=field):
				self.assertEqual(expected[field], job[field])

	def test_add_duplicate_job(self):
		"""
		Test adding duplicate jobs

		Expected: Only one job is added to the database
		"""
		queue = JobQueue(logger=self.log, database=self.db)

		queue.add_job("test", self.jobid)
		queue.add_job("test", self.jobid)

		jobs = queue.get_job_count()
		self.assertEqual(jobs, 1)

	def test_get_job(self):
		"""
		Test if a job can succesfully be gotten from the queue
		"""
		queue = JobQueue(logger=self.log, database=self.db)

		self.db.insert("jobs", self.basic_job)
		job = self.db.fetchone("SELECT * FROM jobs")
		for field in self.basic_expected:
			with self.subTest(field=field):
				self.assertEqual(self.basic_expected[field], job[field])

	def test_claim_job(self):
		"""
		Test claiming a job

		Expected: claim time set to time of claiming
		"""
		queue = JobQueue(logger=self.log, database=self.db)

		queue.add_job("test", remote_id=self.jobid)
		job = queue.get_job("test")

		with self.subTest():
			self.assertIsNotNone(job)

		queue.claim_job(job)

		job = queue.get_job("test")
		with self.subTest():
			self.assertIsNone(job)

		job = self.db.fetchone("SELECT * FROM jobs")
		with self.subTest():
			self.assertIsNotNone(job)

		self.assertGreater(job["claimed"], int(time.time()) - 2)

	def test_claim_job_claimed(self):
		"""
		Test claiming an already claimed job

		Expected: an exception is raised when the job is claimed for the second time
		"""
		queue = JobQueue(logger=self.log, database=self.db)

		queue.add_job("test", remote_id=self.jobid)
		job = queue.get_job("test")
		self.assertIsNotNone(job)

		queue.claim_job(job)
		with self.assertRaises(JobClaimedException):
			queue.claim_job(job)

	def test_release_job(self):
		"""
		Test releasing a job

		Expected: claim time resets, attempts += 1
		"""
		queue = JobQueue(logger=self.log, database=self.db)

		queue.add_job("test", remote_id=self.jobid)
		job = queue.get_job("test")
		with self.subTest():
			self.assertIsNotNone(job)
			queue.claim_job(job)
			queue.release_job(job)

			job = self.db.fetchone("SELECT * FROM jobs")

			with self.subTest():
				self.assertEqual(job["claimed"], 0)

			with self.subTest():
				self.assertEqual(job["attempts"], 1)

	def test_finish_job(self):
		"""
		Test finishing a job

		Expected: job removed from database after finishing
		"""
		queue = JobQueue(logger=self.log, database=self.db)

		queue.add_job("test", remote_id=self.jobid)
		job = queue.get_job("test")

		self.assertIsNotNone(job)

		queue.finish_job(job)
		job = self.db.fetchone("SELECT * FROM jobs")

		self.assertIsNone(job)

	def test_get_all_jobs(self):
		"""
		Test getting all jobs

		Expected: all jobs added are returned
		"""
		queue = JobQueue(logger=self.log, database=self.db)

		expected = 100
		for i in range(0, expected):
			queue.add_job("test", remote_id=self.jobid)
			queue.add_job("test", remote_id=self.jobid + i)

		jobs = queue.get_all_jobs()
		self.assertEqual(len(jobs), expected)

	def test_get_all_jobs_partially_claimed(self):
		"""
		Test getting all jobs while some are claimed

		Expected: all jobs are returned, regardless of claim status
		"""
		queue = JobQueue(logger=self.log, database=self.db)

		queue.add_job("test", remote_id=self.jobid)
		queue.add_job("test", remote_id=self.jobid + 1)

		job = queue.get_job("test")

		self.assertIsNotNone(job)
		queue.claim_job(job)
		jobs = queue.get_all_jobs()
		self.assertEqual(len(jobs), 2)

	def test_get_job_count(self):
		"""
		Test retrieving job count

		Expected: number matches amount of jobs added to queue
		"""
		queue = JobQueue(logger=self.log, database=self.db)

		expected = 100
		for i in range(0, expected):
			queue.add_job("test", remote_id=self.jobid)
			queue.add_job("test", remote_id=self.jobid + i)

		jobs = queue.get_job_count()
		self.assertEqual(jobs, expected)

	def test_release_all(self):
		"""
		Test releasing all jobs

		Expected: before releasing all, claimed jobs > 0, after, == 0
		"""
		queue = JobQueue(logger=self.log, database=self.db)

		expected = 100
		claimable = round(expected / 2)
		for i in range(0, expected):
			queue.add_job("test", remote_id=self.jobid)
			queue.add_job("test", remote_id=self.jobid + i)

		for i in range(0, claimable):
			job = queue.get_job("test")
			with self.subTest():
				self.assertIsNotNone(job)
				queue.claim_job(job)

		unclaimed_jobs = self.db.fetchone("SELECT COUNT(*) AS num FROM jobs WHERE claimed = 0")["num"]
		self.assertEqual(unclaimed_jobs, expected - claimable)

		queue.release_all()
		unclaimed_jobs = self.db.fetchone("SELECT COUNT(*) AS num FROM jobs WHERE claimed = 0")["num"]
		self.assertEqual(unclaimed_jobs, expected)

	def test_release_with_delay(self):
		"""
		Test releasing a job with a reclaim delay

		Expected: releasing a job makes it unclaimable until reclaim delay has passed
		"""
		queue = JobQueue(logger=self.log, database=self.db)

		queue.add_job("test", remote_id=self.jobid)
		job = queue.get_job("test")
		self.assertIsNotNone(job)

		queue.release_job(job, delay=2)

		all_jobs = queue.get_job_count()
		self.assertEqual(all_jobs, 1)

		job = queue.get_job("test")
		self.assertIsNone(job)

		time.sleep(3)
		job = queue.get_job("test")
		self.assertIsNotNone(job)

	def test_release_with_claim_after(self):
		"""
		Test releasing a job with an absolute reclaim delay

		Expected: releasing a job makes it unclaimable until reclaim delay has passed
		"""
		queue = JobQueue(logger=self.log, database=self.db)

		queue.add_job("test", remote_id=self.jobid)
		job = queue.get_job("test")
		self.assertIsNotNone(job)

		deadline = int(time.time()) + 2
		queue.release_job(job, claim_after=deadline)

		all_jobs = queue.get_job_count()
		self.assertEqual(all_jobs, 1)

		job = queue.get_job("test")
		self.assertIsNone(job)

		time.sleep(3)
		job = queue.get_job("test")
		self.assertIsNotNone(job)


if __name__ == '__main__':
	unittest.main()
