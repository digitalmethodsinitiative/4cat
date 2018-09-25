import time
import json
import psycopg2

from .database import Database


class JobQueue:
    """
    A simple job queue

    Jobs are basically database records. The job has some information that a scraper (in
    this case) can use to scrape. The job queue is shared between scrapers so that nothing
    is scraped twice.
    """
    db = None

    def __init__(self):
        """
        Set up database handler
        """
        self.db = Database()

    def getJob(self, type):
        """
        Get job of a specific type

        Returns a job's data. The `details` column is parsed JSON, and can thus contain all
        kinds of data.

        :param string type:  Job type
        :return dict: Job data, or `None` if no job was found
        """
        job = self.db.fetchone("SELECT * FROM jobs WHERE jobtype = %s AND claimed = 0;", (type,))

        return {key: (json.loads(value) if key == "details" else value) for key, value in job.items()} if job else None

    def getJobCount(self, type="*"):
        """
        Get total number of jobs

        :param type:  Type of jobs to count. Default (`*`) counts all jobs.
        :return int:  Number of jobs
        """
        if type == "*":
            count = self.db.fetchone("SELECT COUNT(*) FROM jobs;")
        else:
            count = self.db.fetchone("SELECT COUNT(*) FROM jobs WHERE jobtype = %s;", (type,))

        return int(count["count"])

    def addJob(self, type, details, remote_id=0):
        """
        Add a new job to the queue

        There can only be one job for any combination of job type and remote id. If a job
        already exists for the given combination, a `JobAlreadyExistsException` is raised.

        :param type:  Job type
        :param details:  Job details - may be empty, will be stored as JSON
        :param remote_id:  Remote ID of object to scrape. For example, a post or thread ID
        """
        try:
            self.db.update("INSERT INTO jobs (jobtype, details, timestamp, remote_id) VALUES (%s, %s, %s, %s);",
                           (type, json.dumps(details), time.time(), remote_id))
        except psycopg2.IntegrityError:
            self.db.commit()
            raise JobAlreadyExistsException()

    def finishJob(self, job_id):
        """
        Finish a job

        This deletes the job from the queue and the database.

        :param job_id:  Job ID to finish
        """
        self.db.update("DELETE FROM jobs WHERE id = %s;", (job_id,))

    def releaseJob(self, job_id):
        """
        Release a job

        The job is no longer marked as claimed, and can be claime by a scraper again.

        :param job_id:  Job ID to release
        """
        self.db.update("UPDATE jobs SET claimed = 0 WHERE id = %s;", (job_id,))

    def releaseAll(self):
        """
        Release all jobs

        All claimed jobs are released. This is useful to run when the scraper is restarted.
        """
        self.db.update("UPDATE jobs SET claimed = 0")

    def claimJob(self, job_id):
        """
        Claim a job

        Marks a job as 'claimed', which means no other scrapers may claim the job, and it will not
        be returned when the queue is asked for a new job to do.

        :param job_id: Job ID to claim
        """
        updated_rows = self.db.update("UPDATE jobs SET claimed = %s WHERE id = %s AND claimed = 0;",
                                      (time.time(), job_id))

        if updated_rows == 0:
            raise JobClaimedException("Job is already claimed")


class QueueException(Exception):
    pass


class JobClaimedException(QueueException):
    pass


class JobAlreadyExistsException(QueueException):
    pass
