from flask_login import login_required, current_user
from flask import render_template, request, jsonify

from backend.lib.worker import BasicWorker
from common.lib.dataset import DataSet
from common.lib.exceptions import JobNotFoundException, DataSetNotFoundException
from common.lib.helpers import call_api
from webtool.lib.helpers import Pagination, error, setting_required
from backend.workers.scheduler import Scheduler
from webtool import app, db, config, queue
from common.lib.job import Job
from common.config_manager import ConfigWrapper

config = ConfigWrapper(config, user=current_user, request=request)


@app.route('/scheduler/', defaults={'page': 1})
@login_required
@setting_required("privileges.can_schedule_datasources")
def show_scheduler(page):
    """
    Show scheduled jobs overview

    For each result, some metadata is displayed.

    :return:  Rendered template
    """
    # todo: this should be in a migrate or on startup
    Scheduler.ensure_database(db)

    page_size = 10
    offset = (page - 1) * page_size
    depth = request.args.get("depth", "current")

    # Check for current scheduler jobs; used to check for active status
    scheduler_jobs = queue.get_all_jobs(jobtype="scheduler", restrict_claimable=False)
    scheduler_job_ids = tuple([job.data["id"] for job in scheduler_jobs])

    # Most recent schedulers w/ pagination
    if depth == "all":
        # Get all scheduler jobs
        query = "SELECT scheduler_id, max(created_at) last_created, jobtype, count(dataset_id) datasets FROM scheduled_jobs GROUP BY scheduler_id, jobtype ORDER BY last_created DESC LIMIT %s OFFSET %s"
        replacements = [page_size, offset]
        scheduler_results = db.fetchall(query, tuple(replacements))

        # Total number of scheduler
        query = "SELECT COUNT(DISTINCT scheduler_id) as num FROM scheduled_jobs"
        num_jobs = db.fetchone(query)["num"]

    elif depth == "current" and scheduler_job_ids:
        # Get current scheduler results
        query = "SELECT scheduler_id, max(created_at) last_created, jobtype, count(dataset_id) datasets FROM scheduled_jobs WHERE scheduler_id IN %s GROUP BY scheduler_id, jobtype ORDER BY last_created DESC LIMIT %s OFFSET %s"
        replacements = [scheduler_job_ids, page_size, offset]
        scheduler_results = db.fetchall(query, tuple(replacements))

        # Total number of scheduler
        query = "SELECT COUNT(DISTINCT scheduler_id) as num FROM scheduled_jobs WHERE scheduler_id IN %s"
        replacements = tuple([scheduler_job_ids])
        num_jobs = db.fetchone(query, replacements)["num"]

    else:
        # No scheduler jobs
        scheduler_results = []
        num_jobs = 0

    if not scheduler_results and page != 1:
        return error(404)

    # Prepare pagination
    pagination = Pagination(page, page_size, num_jobs, route="show_scheduler")

    # Collect data for each scheduled job
    scheduler_info = []
    if scheduler_results:
        for scheduler in scheduler_results:
            # Check if active and collect job if so
            if scheduler.get("scheduler_id") in scheduler_job_ids:
                active = True
                # this can be used to update the scheduler job (e.g., change interval)
                scheduler_master_job = [job for job in scheduler_jobs if job.data["id"] == scheduler["scheduler_id"]][0]
            else:
                active = False
                scheduler_master_job = None

            scheduler_info.append({
                "jobtype": scheduler.get("jobtype"),
                "last_created": scheduler.get("last_created"),
                "scheduler_job": scheduler_master_job,
                # "label": scheduler.get("details", {}).get("label", "Query"),
                # "enddate": scheduler.get("details", {}).get("enddate", None),
                "active": active,
                "number_datasets": scheduler.get("datasets"),
                "scheduler_id": scheduler.get("scheduler_id"),
            })

    return render_template("scheduler.html", filter={}, depth=depth,
                           schedulers=scheduler_info, pagination=pagination)

@app.route('/scheduler/<string:scheduler_id>', defaults={'page': 1})
@login_required
def view_scheduler_datasets(scheduler_id, page):
    page_size = 10
    offset = (page - 1) * page_size

    query = "SELECT dataset_id FROM scheduled_jobs WHERE scheduler_id=%s ORDER BY created_at DESC"
    replacements = (scheduler_id,)
    results = db.fetchall(query, replacements)

    datasets = []
    # only instantiate datasets for the current page
    for result in results[offset:offset + page_size]:
        try:
            datasets.append(DataSet(key=result.get("dataset_id"), db=db))
        except DataSetNotFoundException:
            # Dataset may have been deleted, but scheduled_job entry still exists
            pass

    # Prepare pagination
    pagination = Pagination(page, page_size, len(results), route="view_scheduler_datasets", route_args={"scheduler_id": scheduler_id})

    return render_template("scheduler_results.html", filter={}, depth="all",
                           datasets=datasets, pagination=pagination)

@app.route("/api/delete-job/", defaults={"job_id": None}, methods=["DELETE", "GET", "POST"])
@app.route("/api/delete-job/<string:job_id>/", methods=["DELETE", "GET", "POST"])
@login_required
def delete_job(job_id=None):
    """
    Delete a job from the scheduler.

    Only available to administrators and job owners.

    :request-param str key:  ID of the job to delete
    :request-param str ?access_token:  Access token; only required if not
    logged in currently.

    :return: A dictionary with a successful `status`.

    :return-schema: {type=object,properties={status={type=string}}}

    :return-error 404:  If the dataset does not exist.
    """
    job_id = request.form.get("job_id", "") if not job_id else job_id
    try:
        job = Job.get_by_ID(id=job_id, database=db)
    except JobNotFoundException:
        return error(404, error="Job does not exist.")

    # Only admin and job owner can delete; most jobs do not have a owner
    job_owner = job.details.get("owner", None)
    if not config.get("privileges.admin.can_manipulate_all_datasets") and not (job_owner and current_user.get_id() == job_owner):
        return error(403, message="Not allowed")

    # Cancel and delete the job for this one (if it exists)
    try:
        response = call_api("cancel-job", {"remote_id": job.data["remote_id"], "jobtype": job.data["jobtype"], "level": BasicWorker.INTERRUPT_CANCEL})
    except ConnectionRefusedError:
        return error(500,
                     message="The 4CAT backend is not available. Try again in a minute or contact the instance maintainer if the problem persists.")
    # Finish and remove scheduler job
    job.finish(delete=True)

    return jsonify({"status": "success", "job_id": job_id, "api_response": response})