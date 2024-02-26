from flask_login import login_required, current_user
from webtool.lib.helpers import Pagination, error, setting_required
from flask import render_template

from webtool import app, db
import backend
from common.lib.job import Job



@app.route('/scheduler/', defaults={'page': 1})
@login_required
@setting_required("privileges.can_schedule_datasources")
def show_scheduler(page):
    """
    Show scheduled jobs overview

    For each result, some metadata is displayed.

    :return:  Rendered template
    """
    page_size = 20
    offset = (page - 1) * page_size

    # ensure that we're only getting top-level datasets
    where = ["(interval != 0)"] #["(key_parent = '' OR key_parent IS NULL)"]
    replacements = []

    # if config.get("privileges.can_view_all_datasets"):
    #     pass
    #
    # # hide private datasets for non-owners and non-admins,
    # owner_match = tuple([current_user.get_id(), *[f"tag:{t}" for t in current_user.tags]])
    #
    # if not config.get("privileges.can_view_private_datasets"):
    #     where.append(
    #         "(is_private = FALSE OR key IN ( SELECT key FROM datasets_owners WHERE name IN %s AND key = datasets.key))")
    #     replacements.append(owner_match)

    where = " AND ".join(where)

    # first figure out how many datasets this matches
    num_jobs = db.fetchone("SELECT COUNT(*) AS num FROM jobs WHERE " + where, tuple(replacements))["num"]

    # then get the current page of results
    replacements.append(page_size)
    replacements.append(offset)
    query = "SELECT * FROM jobs WHERE " + where + " ORDER BY timestamp DESC LIMIT %s OFFSET %s"

    job_results = db.fetchall(query, tuple(replacements))
    jobs = [Job.get_by_data(job_data, db) for job_data in job_results]

    if not jobs and page != 1:
        return error(404)

    # some housekeeping to prepare data for the template
    pagination = Pagination(page, page_size, num_jobs, route="show_scheduler")
    # filtered = [DataSet(key=dataset["key"], db=db) for dataset in datasets]

    datasources = {datasource: metadata for datasource, metadata in backend.all_modules.datasources.items() if
                   metadata["has_worker"] and metadata["has_options"]}

    return render_template("scheduler.html", filter={}, depth="all", datasources=datasources,
                           jobs=jobs, pagination=pagination)