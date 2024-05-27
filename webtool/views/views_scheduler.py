from flask_login import login_required, current_user

from backend.lib.worker import BasicWorker
from common.lib.dataset import DataSet
from common.lib.exceptions import JobNotFoundException, DataSetNotFoundException
from common.lib.helpers import call_api
from webtool.lib.helpers import Pagination, error, setting_required
from flask import render_template, request, jsonify

from webtool import app, db, config, queue
import backend
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
    page_size = 10
    offset = (page - 1) * page_size
    depth = request.args.get("depth", "current")

    # Check for current scheduler jobs; used to check for active status
    scheduler_jobs = queue.get_all_jobs(jobtype="scheduler", restrict_claimable=False)
    scheduler_job_ids = tuple([job.data["id"] for job in scheduler_jobs])

    # Most recent schedulers w/ pagination
    if depth == "all":
        # Get all scheduler jobs
        query = "SELECT scheduler_id, max(created_at) last_created, jobtype FROM scheduled_jobs GROUP BY scheduler_id, jobtype LIMIT %s OFFSET %s"
        replacements = [page_size, offset]
        scheduler_results = db.fetchall(query, tuple(replacements))

        # Total number of scheduler
        query = "SELECT COUNT(DISTINCT scheduler_id) as num FROM scheduled_jobs"
        num_jobs = db.fetchone(query)["num"]

    elif depth == "current" and scheduler_job_ids:
        # Get current scheduler results
        query = "SELECT scheduler_id, max(created_at) last_created, jobtype FROM scheduled_jobs WHERE scheduler_id IN %s GROUP BY scheduler_id, jobtype LIMIT %s OFFSET %s"
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
        query = "SELECT * FROM scheduled_jobs WHERE scheduler_id IN %s ORDER BY created_at DESC"
        replacements = [tuple([scheduler["scheduler_id"] for scheduler in scheduler_results])]
        scheduled_job_results = db.fetchall(query, tuple(replacements))

        for scheduler in scheduler_results:
            # Check if active and collect job if so
            if scheduler.get("scheduler_id") in scheduler_job_ids:
                active = True
            else:
                active = False
            related_jobs = [job for job in scheduled_job_results if job["scheduler_id"] == scheduler["scheduler_id"]]
            # datasets = []
            # for job in scheduled_job_results:
            #     if job["scheduler_id"] == scheduler["scheduler_id"]:
            #         try:
            #             datasets.append(DataSet(key=job.get('dataset_id'), db=db))
            #         except DataSetNotFoundException:
            #             # Dataset may have been deleted, but scheduled_job entry still exists
            #             pass
            scheduler_info.append({
                "jobtype": scheduler.get("jobtype"),
                "last_created": scheduler.get("last_created"),
                # TODO: do not have these from current groupby query...
                # "label": scheduler.get("details", {}).get("label", "Query"),
                # "enddate": scheduler.get("details", {}).get("enddate", None),
                "active": active,
                "number_datasets": len(related_jobs),
                "scheduler_id": scheduler.get("scheduler_id"),
                "datasets": related_jobs,
            })

    datasources = {datasource: metadata for datasource, metadata in backend.all_modules.datasources.items() if
                   metadata["has_worker"] and metadata["has_options"]}

    return render_template("scheduler.html", filter={}, depth=depth, datasources=datasources,
                           jobs=scheduler_info, pagination=pagination)


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