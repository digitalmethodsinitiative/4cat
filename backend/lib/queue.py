"""
A job queue, to divide work over the workers
"""
import time
import json

from lib.database import Database


class JobQueue:
    """
    A simple job queue

    Jobs are basically database records. The job has some information that a worker
    can use to do its job. The job queue is shared between workers so that nothing
    is done twice.
    """
    db = None
    log = None

    def __init__(self, logger):
        """
        Set up database handler
        """
        self.log = logger

        self.db = Database(logger=self.log)

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
        job = self.db.fetchone("SELECT * FROM jobs WHERE jobtype = %s AND claimed = 0 AND claim_after < %s;",
                               (jobtype, timestamp))

        return {key: (json.loads(value) if key == "details" else value) for key, value in job.items()} if job else None

    def get_all_jobs(self):
        """
        Get all jobs

        Returns all jobs, no matter the type or claim-after date

        :return list:
        """
        return self.db.fetchall("SELECT * FROM jobs")

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

    def add_job(self, jobtype, details=None, remote_id=0, claim_after=0):
        """
        Add a new job to the queue

        There can only be one job for any combination of job type and remote id. If a job
        already exists for the given combination, no new job is added.

        :param jobtype:  Job type
        :param details:  Job details - may be empty, will be stored as JSON
        :param remote_id:  Remote ID of object to work on. For example, a post or thread ID
        """
        self.db.insert("jobs", data={
            "jobtype": jobtype,
            "details": json.dumps(details),
            "timestamp": int(time.time()),
            "remote_id": remote_id,
            "claim_after": claim_after
        }, safe=True, constraints=("jobtype", "remote_id"))

    def finish_job(self, job):
        """
        Finish a job

        This deletes the job from the queue and the database.

        :param job:  Job to finish
        """
        self.db.delete("jobs", where={"id": job["id"]})

    def release_job(self, job, delay=0, claim_after=0):
        """
        Release a job

        The job is no longer marked as claimed, and can be claimed by a worker again.

        :param job:  Job to release
        :param int delay:  Amount of seconds after which job may be reclaimed
        :param int claim_after:  UNIX timestamp after which job may be reclaimed. If
                                `delay` is set, it overrides this parameter.
        """
        if delay > 0:
            claim_after = int(time.time()) + delay

        self.db.update("jobs", where={"id": job["id"]}, data={"claimed": 0, "claim_after": claim_after})

    def release_all(self):
        """
        Release all jobs

        All claimed jobs are released. This is useful to run when the backend is restarted.
        """
        self.db.execute("UPDATE jobs SET claimed = 0")

    def claim_job(self, job):
        """
        Claim a job

        Marks a job as 'claimed', which means no other workers may claim the job, and it will not
        be returned when the queue is asked for a new job to do.

        :param job: Job to claim
        """
        updated_rows = self.db.update("jobs", where={"id": job["id"], "claimed": 0},
                                      data={"claimed": int(time.time()), "attempts": job["attempts"] + 1})

        if updated_rows == 0:
            raise JobClaimedException("Job is already claimed")


class QueueException(Exception):
    """
    General Queue Exception - only children are to be used
    """
    pass


class JobClaimedException(QueueException):
    """
    Raise if job is claimed, but is already marked as such
    """
    pass


class JobAlreadyExistsException(QueueException):
    """
    Raise if a job is created, but a job with the same type/remote_id combination already exists
    """
    pass
