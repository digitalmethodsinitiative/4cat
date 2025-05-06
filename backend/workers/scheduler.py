"""
Schedule processors on a regular basis
"""
import json
from datetime import datetime

from backend.lib.worker import BasicWorker
from common.lib.dataset import DataSet
from common.lib.job import Job


class Scheduler(BasicWorker):
	"""
	Similar to the manager, this worker schedules other workers to run at regular intervals. This worker will maintain
	the schedule for related jobs. If a job does not complete successfully, it will be rescheduled according to some
	criteria. Primarily, this worker is different from a normal job run at intervals in that it maintains a relationship
	between multiple jobs which otherwise does not exist and allows us to maintain the one to one relationship between
	job, processors, and datasets.
	"""
	type = "scheduler"
	max_workers = 5 # this seems a bit arbitrary, we can run many and this should only be updating the database and creating other jobs as necessary
	work_report = None
	details = None

	@staticmethod
	def ensure_database(db):
		"""
		Ensure that the database is set up for this worker

		job_id: primary key of each scheduled job
		scheduler_id: job id of the original scheduler
		jobtype: type of job to be run
		dataset_id: dataset id for each specific job
		status: status of the job
		last_run: last time the job was run
		details: additional details for the job (potentially different for each job)
		"""
		# create the table if it doesn't exist
		db.execute("CREATE TABLE IF NOT EXISTS scheduled_jobs (job_id int PRIMARY KEY, scheduler_id int NOT NULL, jobtype text NOT NULL, dataset_id text NOT NULL, status text NOT NULL, created_at integer, details jsonb)")

	def work(self):
		"""
		Check previous scheduled jobs and schedule new ones as necessary
		"""
		# TODO: ensure_database could be called when workers are validated; we could even check for packages there
		self.ensure_database(self.db)
		# Ensure clean work report
		self.work_report = {}

		# Get job details
		self.details = self.job.details
		self.log.debug(f"Scheduler started: {self.details}")

		# get this worker's previously scheduled jobs, order by last run
		jobs = self.db.fetchall("SELECT * FROM scheduled_jobs where scheduler_id = %s", (self.job.data["id"],))

		if not jobs:
			# No jobs, schedule first one
			self.schedule_job(first=True)
		else:
			# Check to see if jobs need to be rescheduled and do so
			self.reschedule_jobs(jobs)

			# Check to see if time for new job and schedule if necessary,
			if self.check_schedule(jobs):
				self.schedule_job()

		if self.check_last_run():
			# If last job has been scheduled, all jobs completed and updated, delete this Scheduler job
			self.job.finish(delete=True)
		else:
			self.job.finish()

	def check_schedule(self, jobs):
		"""
		Check if it is time to schedule a new job

		:param list jobs: List of jobs
		:return bool: Whether to schedule a new job
		"""
		# Currently main job is scheduled by Manager, so we don't need to check for it
		return True

	def schedule_job(self, first=False):
		"""
		Schedule a new job

		TODO: How should we handle sensitive data in a Scheduler type scenario? I feel that we should allow it,
		but perhaps have a warning popup? Right now, I'm looking at storing dataset parameters in the job.details
		column and they may contain parameters. I thought I could perhaps get away with using the latest dataset
		created by the Scheduler (I am not sure how to do this yet, but I want to be able to update some parameters
		such as dates if we were to say want a rolling start date for a query)

		:param bool first: Whether this is the first job
		"""
		if first:
			# Schedule the first job; dataset already exists
			dataset = DataSet(key=self.job.data["remote_id"].replace("scheduler-",""), db=self.db, modules=self.modules)

			# Dataset processor
			processor = dataset.get_own_processor()

			# Store necessaries for future datasets
			# These may contain sensitive parameters, but those will be needed for future jobs...
			given_parameters = dataset.parameters.copy()
			all_parameters = processor.get_options(dataset)
			parameters = {
				param: given_parameters.get(param, all_parameters.get(param, {}).get("default"))
				for param in [*all_parameters.keys(), *given_parameters.keys()]
			}
			self.update_details({
				"owner": dataset.creator,
				"processor_type": processor.type,
				"extension": processor.get_extension(dataset.get_parent()),
				"is_private": dataset.is_private,
				"parameters": dataset.parameters.copy(),
				"label": dataset.get_label(),
				"last_dataset": dataset.key
			})

		else:
			# Create new dataset
			dataset = DataSet(
				parameters=self.details.get("parameters"),
				db=self.db,
				type=self.details.get("processor_type"),
				extension=self.details.get("extension"),
				is_private=self.details.get("is_private"),
				owner=self.details.get("owner"),
				modules=self.modules
			)
			self.update_details({"last_dataset": dataset.key})

		# Create new job; interval is 0 as this scheduler is responsible for scheduling the next job
		# Job details contains the scheduler_id for job to update scheduler table on finish
		self.queue.add_job(jobtype=self.details.get("processor_type"), remote_id=dataset.key, interval=0, details={"scheduler_id": self.job.data["id"]})
		# Get new job w/ ID
		new_job = Job.get_by_remote_ID(dataset.key, self.db)

		# Link new job to dataset
		dataset.link_job(new_job)

		# Update scheduler table
		self.db.insert("scheduled_jobs", data={
			"job_id": new_job.data["id"],
			"scheduler_id": self.job.data["id"],
			"jobtype": self.details.get("processor_type"),
			"dataset_id": dataset.key,
			"status": "scheduled",
			"created_at": int(datetime.now().timestamp()),
			"details": json.dumps(self.details)
		})
		self.log.info(f"Scheduler created {self.details.get('processor_type')} job: dataset {self.details.get('last_dataset')}")

	def update_details(self, details):
		"""
		Update parameters for the next job. If none exist, create them.

		Unsure if I want this, but we could allow users to update the parameters for the next job
		"""
		self.details.update(details)
		self.db.update("jobs", where={"jobtype": self.job.data["jobtype"], "remote_id": self.job.data["remote_id"]},
					   data={"details": json.dumps(self.details)})

	def reschedule_jobs(self, jobs):
		"""
		Reschedule jobs that need it

		:param list jobs: List of jobs
		"""
		pass

	def check_last_run(self):
		"""
		Check if the last job has been run

		:return bool:
		"""
		end_date = self.details.get("enddate")
		if end_date and datetime.now() >= datetime.strptime(end_date, "%Y-%m-%d"):
			return True
		else:
			return False